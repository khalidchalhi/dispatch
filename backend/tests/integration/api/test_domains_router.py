from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient

from apps.api.deps import (
    get_auth_service_dep,
    get_domain_service_dep,
    get_sender_profile_service_dep,
    get_settings_dep,
    get_user_service_dep,
    get_warmup_service_dep,
)
from apps.api.main import app
from libs.core.domains.provisioning import ProvisioningStep
from libs.core.domains.schemas import DnsRecordType
from libs.core.domains.service import DomainProvisioningAuditEntry, DomainZone

AuthTestContext = Any
UserFactory = Any


@pytest.fixture
async def auth_client(auth_test_context: AuthTestContext) -> AsyncIterator[AsyncClient]:
    app.dependency_overrides[get_settings_dep] = lambda: auth_test_context.settings
    app.dependency_overrides[get_auth_service_dep] = lambda: auth_test_context.auth_service
    app.dependency_overrides[get_user_service_dep] = lambda: auth_test_context.user_service
    app.dependency_overrides[get_domain_service_dep] = lambda: auth_test_context.domain_service
    app.dependency_overrides[get_warmup_service_dep] = lambda: auth_test_context.warmup_service
    app.dependency_overrides[get_sender_profile_service_dep] = (
        lambda: auth_test_context.sender_profile_service
    )
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client
    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_domains_router_create_verify_retire_roundtrip(
    auth_client: AsyncClient,
    auth_test_context: AuthTestContext,
    auth_user_factory: UserFactory,
) -> None:
    await auth_user_factory(
        email="admin-domains@example.com",
        password="correct-password-value",
        role="admin",
    )

    login_response = await auth_client.post(
        "/auth/login",
        json={"email": "admin-domains@example.com", "password": "correct-password-value"},
    )
    assert login_response.status_code == 200

    create_response = await auth_client.post(
        "/domains",
        json={
            "name": "api.dispatch.test",
            "dns_provider": "manual",
            "parent_domain": "dispatch.test",
            "ses_region": "us-east-1",
            "default_configuration_set_name": "api-default",
        },
    )
    assert create_response.status_code == 201
    create_payload = create_response.json()
    domain_id = create_payload["id"]
    dns_records = create_payload["dns_records"]
    assert len(dns_records) >= 6

    list_response = await auth_client.get("/domains")
    assert list_response.status_code == 200
    assert any(item["id"] == domain_id for item in list_response.json()["items"])

    get_response = await auth_client.get(f"/domains/{domain_id}")
    assert get_response.status_code == 200
    assert get_response.json()["name"] == "api.dispatch.test"

    for record in dns_records:
        auth_test_context.dns_adapter.set_record(
            record_type=DnsRecordType(record["record_type"]),
            name=record["name"],
            values=[record["value"]],
        )

    verify_response = await auth_client.post(f"/domains/{domain_id}/verify")
    assert verify_response.status_code == 200
    verify_payload = verify_response.json()
    assert verify_payload["fully_verified"] is True
    assert verify_payload["domain"]["verification_status"] == "verified"

    retire_response = await auth_client.post(
        f"/domains/{domain_id}/retire",
        json={"reason": "domain lifecycle complete"},
    )
    assert retire_response.status_code == 200
    assert retire_response.json()["message"] == "Domain retired"


@pytest.mark.asyncio
async def test_domains_router_updates_throttle_rate_limit(
    auth_client: AsyncClient,
    auth_user_factory: UserFactory,
) -> None:
    await auth_user_factory(
        email="admin-throttle@example.com",
        password="correct-password-value",
        role="admin",
    )

    login_response = await auth_client.post(
        "/auth/login",
        json={"email": "admin-throttle@example.com", "password": "correct-password-value"},
    )
    assert login_response.status_code == 200

    create_response = await auth_client.post(
        "/domains",
        json={
            "name": "throttle.dispatch.test",
            "dns_provider": "manual",
            "parent_domain": "dispatch.test",
            "ses_region": "us-east-1",
            "default_configuration_set_name": "api-default",
        },
    )
    assert create_response.status_code == 201
    domain_id = create_response.json()["id"]

    update_response = await auth_client.post(
        f"/domains/{domain_id}/throttle",
        json={"rate_limit_per_hour": 750},
    )
    assert update_response.status_code == 200
    assert update_response.json()["rate_limit_per_hour"] == 750

    get_response = await auth_client.get(f"/domains/{domain_id}")
    assert get_response.status_code == 200
    assert get_response.json()["rate_limit_per_hour"] == 750

    invalid_response = await auth_client.post(
        f"/domains/{domain_id}/throttle",
        json={"rate_limit_per_hour": 0},
    )
    assert invalid_response.status_code == 422


@pytest.mark.asyncio
async def test_domains_router_provisioning_endpoints_enqueue_and_status(
    auth_client: AsyncClient,
    auth_user_factory: UserFactory,
    monkeypatch: Any,
) -> None:
    await auth_user_factory(
        email="admin-provision@example.com",
        password="correct-password-value",
        role="admin",
    )

    login_response = await auth_client.post(
        "/auth/login",
        json={"email": "admin-provision@example.com", "password": "correct-password-value"},
    )
    assert login_response.status_code == 200

    create_response = await auth_client.post(
        "/domains",
        json={
            "name": "provision-api.dispatch.test",
            "dns_provider": "cloudflare",
            "parent_domain": "dispatch.test",
            "ses_region": "us-east-1",
            "default_configuration_set_name": "api-default",
        },
    )
    assert create_response.status_code == 201
    domain_id = create_response.json()["id"]

    task_calls: list[dict[str, Any]] = []

    def _fake_send_task(task_name: str, *, kwargs: dict[str, str]) -> None:
        task_calls.append({"task_name": task_name, "kwargs": kwargs})

    monkeypatch.setattr("apps.api.routers.domains.celery_app.send_task", _fake_send_task)

    provision_response = await auth_client.post(
        f"/domains/{domain_id}/provision",
        json={"force": False},
    )
    assert provision_response.status_code == 202
    provision_payload = provision_response.json()
    assert provision_payload["domain_id"] == domain_id
    assert provision_payload["status"] == "queued"
    assert len(task_calls) == 1
    assert task_calls[0]["task_name"] == "domains.provision_domain"
    assert task_calls[0]["kwargs"]["domain_id"] == domain_id
    assert task_calls[0]["kwargs"]["run_id"] == provision_payload["run_id"]

    status_response = await auth_client.get(f"/domains/{domain_id}/provisioning-status")
    assert status_response.status_code == 200
    status_payload = status_response.json()
    assert status_payload["domain_id"] == domain_id
    assert status_payload["run_id"] == provision_payload["run_id"]
    assert status_payload["status"] == "queued"
    assert any(
        step["name"] == "queued" and step["status"] == "queued"
        for step in status_payload["steps"]
    )


@pytest.mark.asyncio
async def test_domains_router_list_zones(
    auth_client: AsyncClient,
    auth_user_factory: UserFactory,
    monkeypatch: Any,
) -> None:
    await auth_user_factory(
        email="admin-zones@example.com",
        password="correct-password-value",
        role="admin",
    )
    login_response = await auth_client.post(
        "/auth/login",
        json={"email": "admin-zones@example.com", "password": "correct-password-value"},
    )
    assert login_response.status_code == 200

    async def _fake_list_zones(
        self: Any,
        *,
        actor: Any,
        provider: str,
    ) -> list[DomainZone]:
        _ = self
        _ = actor
        return [DomainZone(id="zone-1", name="dispatch.test", provider="cloudflare")]

    monkeypatch.setattr(
        "libs.core.domains.service.DomainService.list_zones_for_provider",
        _fake_list_zones,
    )
    response = await auth_client.get("/domains/zones?provider=cloudflare")
    assert response.status_code == 200
    payload = response.json()
    assert payload["items"] == [
        {"id": "zone-1", "name": "dispatch.test", "provider": "cloudflare"}
    ]


@pytest.mark.asyncio
async def test_ops_provisioning_router_returns_audit_feed(
    auth_client: AsyncClient,
    auth_user_factory: UserFactory,
    monkeypatch: Any,
) -> None:
    await auth_user_factory(
        email="admin-ops@example.com",
        password="correct-password-value",
        role="admin",
    )
    login_response = await auth_client.post(
        "/auth/login",
        json={"email": "admin-ops@example.com", "password": "correct-password-value"},
    )
    assert login_response.status_code == 200

    async def _fake_list_audit(
        self: Any,
        *,
        actor: Any,
        limit: int = 50,
    ) -> list[DomainProvisioningAuditEntry]:
        _ = self
        _ = (actor, limit)
        return [
            DomainProvisioningAuditEntry(
                id="run-1",
                domain_id="domain-1",
                domain_name="mail.dispatch.test",
                provider="cloudflare",
                status="failed",
                reason_code="dns_record_apply_failed",
                started_at=None,
                completed_at=None,
                steps=[
                    ProvisioningStep(
                        name="apply_dns_records",
                        status="failed",
                        at=datetime.now(UTC),
                        message="dns apply failed",
                    )
                ],
            )
        ]

    monkeypatch.setattr(
        "libs.core.domains.service.DomainService.list_provisioning_audit",
        _fake_list_audit,
    )
    response = await auth_client.get("/ops/provisioning")
    assert response.status_code == 200
    payload = response.json()
    assert len(payload["items"]) == 1
    assert payload["items"][0]["id"] == "run-1"
    assert payload["items"][0]["reason_code"] == "dns_record_apply_failed"


@pytest.mark.asyncio
async def test_domains_router_get_warmup_status(
    auth_client: AsyncClient,
    auth_test_context: AuthTestContext,
    auth_user_factory: UserFactory,
) -> None:
    await auth_user_factory(
        email="admin-warmup@example.com",
        password="correct-password-value",
        role="admin",
    )
    login_response = await auth_client.post(
        "/auth/login",
        json={"email": "admin-warmup@example.com", "password": "correct-password-value"},
    )
    assert login_response.status_code == 200

    create_response = await auth_client.post(
        "/domains",
        json={
            "name": "warmup-status.dispatch.test",
            "dns_provider": "manual",
            "parent_domain": "dispatch.test",
            "ses_region": "us-east-1",
            "default_configuration_set_name": "api-default",
        },
    )
    assert create_response.status_code == 201
    domain_id = create_response.json()["id"]

    await auth_test_context.warmup_service.start_warmup(
        domain_id=domain_id,
        schedule_volumes=[50, 100, 500],
    )

    response = await auth_client.get(f"/domains/{domain_id}/warmup")
    assert response.status_code == 200
    payload = response.json()
    assert payload["domain_id"] == domain_id
    assert payload["warmup_stage"] == "warming"
    assert payload["total_days"] == 3
    assert payload["today_cap"] == 50
    assert len(payload["schedule"]["days"]) == 3


@pytest.mark.asyncio
async def test_domains_router_extend_warmup(
    auth_client: AsyncClient,
    auth_test_context: AuthTestContext,
    auth_user_factory: UserFactory,
) -> None:
    await auth_user_factory(
        email="admin-warmup-extend@example.com",
        password="correct-password-value",
        role="admin",
    )
    login_response = await auth_client.post(
        "/auth/login",
        json={
            "email": "admin-warmup-extend@example.com",
            "password": "correct-password-value",
        },
    )
    assert login_response.status_code == 200

    create_response = await auth_client.post(
        "/domains",
        json={
            "name": "warmup-extend.dispatch.test",
            "dns_provider": "manual",
            "parent_domain": "dispatch.test",
            "ses_region": "us-east-1",
            "default_configuration_set_name": "api-default",
        },
    )
    assert create_response.status_code == 201
    domain_id = create_response.json()["id"]

    started = await auth_test_context.warmup_service.start_warmup(
        domain_id=domain_id,
        schedule_volumes=[50, 100, 500],
    )
    assert started.warmup_schedule == [50, 100, 500]

    extend_response = await auth_client.post(
        f"/domains/{domain_id}/warmup/extend",
        json={"days": 2},
    )
    assert extend_response.status_code == 200
    assert extend_response.json()["message"] == "Warmup extended"

    status_response = await auth_client.get(f"/domains/{domain_id}/warmup")
    assert status_response.status_code == 200
    payload = status_response.json()
    assert payload["total_days"] == 5
