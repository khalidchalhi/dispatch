from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4

import pytest

from apps.workers import domain_tasks
from libs.core.auth.schemas import CurrentActor
from libs.core.domains.provisioning import SesIdentityState
from libs.core.domains.schemas import DnsRecordType
from libs.core.domains.service import DomainService
from libs.core.errors import ExternalServiceError
from libs.dns_provisioner.base import DNSProvisioner, DNSRecordInput, DNSZone

AuthTestContext = Any
UserFactory = Any


@dataclass(slots=True)
class _FakeDnsProvisioner(DNSProvisioner):
    fail_on_create: bool = False
    records: dict[str, dict[str, DNSRecordInput]] = field(default_factory=dict)
    counter: int = 0

    async def create_record(self, *, zone_id: str, record: DNSRecordInput) -> str:
        if self.fail_on_create:
            raise ExternalServiceError("dns apply failed")
        zone_records = self.records.setdefault(zone_id, {})
        for record_id, existing in zone_records.items():
            if (
                existing.record_type == record.record_type
                and existing.name == record.name
                and existing.value == record.value
            ):
                return record_id
        self.counter += 1
        record_id = f"r-{self.counter}"
        zone_records[record_id] = record
        return record_id

    async def update_record(self, *, zone_id: str, record_id: str, record: DNSRecordInput) -> str:
        zone_records = self.records.setdefault(zone_id, {})
        zone_records[record_id] = record
        return record_id

    async def delete_record(self, *, zone_id: str, record_id: str) -> None:
        self.records.setdefault(zone_id, {}).pop(record_id, None)

    async def verify_record(self, *, zone_id: str, record: DNSRecordInput) -> bool:
        zone_records = self.records.setdefault(zone_id, {})
        return any(
            existing.record_type == record.record_type
            and existing.name == record.name
            and existing.value == record.value
            for existing in zone_records.values()
        )

    async def list_zones(self) -> list[DNSZone]:
        return [DNSZone(id="zone-1", name="dispatch.test")]


@dataclass(slots=True)
class _FakeSesProvisioner:
    polls_until_verified: int = 1
    poll_calls: int = 0

    async def ensure_identity(self, *, domain_name: str) -> SesIdentityState:
        _ = domain_name
        return SesIdentityState(
            identity_arn="arn:aws:ses:us-east-1:000000000000:identity/test",
            verified_for_sending=False,
            dkim_tokens=["token1", "token2", "token3"],
            dkim_signing_enabled=False,
        )

    async def get_identity_state(self, *, domain_name: str) -> SesIdentityState:
        _ = domain_name
        self.poll_calls += 1
        verified = self.poll_calls >= self.polls_until_verified
        return SesIdentityState(
            identity_arn="arn:aws:ses:us-east-1:000000000000:identity/test",
            verified_for_sending=verified,
            dkim_tokens=["token1", "token2", "token3"],
            dkim_signing_enabled=verified,
        )

    async def ensure_configuration_set(self, *, name: str, sns_topic_arn: str | None) -> None:
        _ = (name, sns_topic_arn)

    async def ensure_mail_from(self, *, domain_name: str, mail_from_domain: str) -> None:
        _ = (domain_name, mail_from_domain)

    async def delete_identity(self, *, domain_name: str) -> None:
        _ = domain_name


class _TestDomainService(DomainService):
    def __init__(
        self,
        *args: object,
        dns_provisioner: DNSProvisioner,
        **kwargs: object,
    ) -> None:
        super().__init__(*args, **kwargs)
        self._fake_dns_provisioner = dns_provisioner

    async def _resolve_dns_provisioner(self, *, domain: Any) -> tuple[DNSProvisioner, str]:
        _ = domain
        return self._fake_dns_provisioner, "zone-1"


async def _create_admin_actor(auth_user_factory: UserFactory) -> CurrentActor:
    user = await auth_user_factory(
        email=f"provision-admin-{uuid4().hex[:8]}@dispatch.test",
        password="provision-password",
        role="admin",
    )
    return CurrentActor(actor_type="user", user=user)


async def _create_cloudflare_domain(
    auth_test_context: AuthTestContext,
    *,
    actor: CurrentActor,
) -> str:
    detail = await auth_test_context.domain_service.create_domain(
        actor=actor,
        name=f"provision-{uuid4().hex[:8]}.dispatch.test",
        dns_provider="cloudflare",
        parent_domain="dispatch.test",
        ses_region="us-east-1",
        default_configuration_set_name=None,
        event_destination_sns_topic_arn="arn:aws:sns:us-east-1:000000000000:dispatch-local-events",
        ip_address=None,
        user_agent=None,
    )
    # Preserve manual verify ability for legacy paths.
    for record in detail.dns_records:
        auth_test_context.dns_adapter.set_record(
            record_type=DnsRecordType(record.record_type),
            name=record.name,
            values=[record.value],
        )
    return detail.domain.id


@pytest.mark.asyncio
async def test_worker_provision_domain_flow_success(
    auth_test_context: AuthTestContext,
    auth_user_factory: UserFactory,
    monkeypatch: Any,
) -> None:
    actor = await _create_admin_actor(auth_user_factory)
    domain_id = await _create_cloudflare_domain(auth_test_context, actor=actor)

    fake_dns = _FakeDnsProvisioner()
    fake_ses = _FakeSesProvisioner(polls_until_verified=1)
    service = _TestDomainService(
        auth_test_context.settings.model_copy(
            update={
                "domain_provisioning_poll_interval_seconds": 1,
                "domain_provisioning_timeout_seconds": 30,
            }
        ),
        dns_verifier=auth_test_context.dns_adapter,
        ses_provisioner=fake_ses,
        dns_provisioner=fake_dns,
        sleep=lambda _seconds: asyncio.sleep(0),
    )

    enqueue = await service.enqueue_domain_provisioning(
        actor=actor,
        domain_id=domain_id,
        force=False,
        ip_address=None,
        user_agent=None,
    )
    monkeypatch.setattr(domain_tasks, "get_domain_service", lambda: service)

    result = domain_tasks.provision_domain(domain_id, enqueue.run_id)
    assert result["status"] == "verified"

    refreshed = await service.get_domain(domain_id)
    assert refreshed.domain.verification_status == "verified"
    assert refreshed.domain.dkim_status == "verified"
    status = await service.get_domain_provisioning_status(domain_id=domain_id)
    assert status.status == "verified"
    assert any(step.name == "complete" for step in status.steps)


@pytest.mark.asyncio
async def test_worker_provision_domain_flow_failure_sets_provisioning_failed(
    auth_test_context: AuthTestContext,
    auth_user_factory: UserFactory,
    monkeypatch: Any,
) -> None:
    actor = await _create_admin_actor(auth_user_factory)
    domain_id = await _create_cloudflare_domain(auth_test_context, actor=actor)

    fake_dns = _FakeDnsProvisioner(fail_on_create=True)
    fake_ses = _FakeSesProvisioner(polls_until_verified=1)
    service = _TestDomainService(
        auth_test_context.settings.model_copy(
            update={
                "domain_provisioning_poll_interval_seconds": 1,
                "domain_provisioning_timeout_seconds": 30,
            }
        ),
        dns_verifier=auth_test_context.dns_adapter,
        ses_provisioner=fake_ses,
        dns_provisioner=fake_dns,
        sleep=lambda _seconds: asyncio.sleep(0),
    )

    enqueue = await service.enqueue_domain_provisioning(
        actor=actor,
        domain_id=domain_id,
        force=False,
        ip_address=None,
        user_agent=None,
    )
    monkeypatch.setattr(domain_tasks, "get_domain_service", lambda: service)

    result = domain_tasks.provision_domain(domain_id, enqueue.run_id)
    assert result["status"] == "failed"
    assert result["reason_code"] == "dns_record_apply_failed"

    refreshed = await service.get_domain(domain_id)
    assert refreshed.domain.verification_status == "provisioning_failed"
    status = await service.get_domain_provisioning_status(domain_id=domain_id)
    assert status.status == "failed"
    assert status.reason_code == "dns_record_apply_failed"


@pytest.mark.parametrize(
    ("failing_step", "expected_reason"),
    [
        ("create_ses_identity", "ses_identity_setup_failed"),
        ("ensure_configuration_set", "ses_configuration_set_failed"),
        ("configure_mail_from", "ses_mail_from_failed"),
        ("sync_dns_records", "dns_record_sync_failed"),
        ("apply_dns_records", "dns_record_apply_failed"),
        ("poll_ses_verification", "ses_verification_failed"),
        ("verify_dns_state", "dns_verification_failed"),
    ],
)
@pytest.mark.asyncio
async def test_worker_provision_domain_flow_chaos_step_failures(
    failing_step: str,
    expected_reason: str,
    auth_test_context: AuthTestContext,
    auth_user_factory: UserFactory,
    monkeypatch: Any,
) -> None:
    actor = await _create_admin_actor(auth_user_factory)
    domain_id = await _create_cloudflare_domain(auth_test_context, actor=actor)

    fake_dns = _FakeDnsProvisioner()
    fake_ses = _FakeSesProvisioner(polls_until_verified=1)
    service = _TestDomainService(
        auth_test_context.settings.model_copy(
            update={
                "domain_provisioning_poll_interval_seconds": 1,
                "domain_provisioning_timeout_seconds": 30,
            }
        ),
        dns_verifier=auth_test_context.dns_adapter,
        ses_provisioner=fake_ses,
        dns_provisioner=fake_dns,
        sleep=lambda _seconds: asyncio.sleep(0),
    )
    original_run_step = service._run_provisioning_step

    async def _inject_failure[T](
        *,
        domain_id: str,
        run_id: str,
        step_name: str,
        step_fn: Any,
    ) -> T:
        if step_name == failing_step:
            async def _always_fail() -> Any:
                raise ExternalServiceError(f"Injected failure at step: {step_name}")

            return await original_run_step(
                domain_id=domain_id,
                run_id=run_id,
                step_name=step_name,
                step_fn=_always_fail,
            )
        return await original_run_step(
            domain_id=domain_id,
            run_id=run_id,
            step_name=step_name,
            step_fn=step_fn,
        )

    monkeypatch.setattr(service, "_run_provisioning_step", _inject_failure)

    enqueue = await service.enqueue_domain_provisioning(
        actor=actor,
        domain_id=domain_id,
        force=False,
        ip_address=None,
        user_agent=None,
    )
    monkeypatch.setattr(domain_tasks, "get_domain_service", lambda: service)

    result = domain_tasks.provision_domain(domain_id, enqueue.run_id)
    assert result["status"] == "failed"
    assert result["reason_code"] == expected_reason

    refreshed = await service.get_domain(domain_id)
    assert refreshed.domain.verification_status == "provisioning_failed"
    status = await service.get_domain_provisioning_status(domain_id=domain_id)
    assert status.status == "failed"
    assert status.reason_code == expected_reason
    assert any(step.name == failing_step and step.status == "running" for step in status.steps)
    assert any(step.name == "failed" and step.status == "failed" for step in status.steps)
