from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from functools import lru_cache
from typing import Literal
from uuid import uuid4

from sqlalchemy import select

from libs.core.auth.models import AuditLog
from libs.core.auth.repository import AuthRepository
from libs.core.auth.schemas import CurrentActor
from libs.core.config import Settings, get_settings
from libs.core.db.session import get_session_factory
from libs.core.db.uow import UnitOfWork
from libs.core.domains.models import Domain, DomainDnsRecord, IPPool, SESConfigurationSet
from libs.core.domains.provisioning import (
    Boto3SesDomainProvisioner,
    DomainProvisioningFailureReason,
    DomainProvisioningStatus,
    ProvisioningStep,
    SesDomainProvisioner,
)
from libs.core.domains.repository import DomainRepository
from libs.core.domains.schemas import (
    DnsRecordType,
    ExpectedDnsRecord,
    IPPoolCreateRequest,
    SESConfigurationSetCreateRequest,
)
from libs.core.errors import (
    ConflictError,
    ExternalServiceError,
    NotFoundError,
    PermissionDeniedError,
    ValidationError,
)
from libs.core.logging import get_logger
from libs.dns_provisioner.base import (
    AwsSecretsManagerSecretProvider,
    DNSProvisioner,
    DnsPythonVerificationAdapter,
    DNSRecordInput,
    DNSVerificationAdapter,
    ZoneNotFoundError,
    normalize_dns_value,
)
from libs.dns_provisioner.cloudflare import CloudflareDNSProvisioner
from libs.dns_provisioner.route53 import Route53DNSProvisioner

logger = get_logger("core.domains")

_PROVISIONING_METADATA_KEY = "provisioning"
_PROVISIONING_STATUSES = {"queued", "running", "verified", "failed", "not_started"}
_DEFAULT_PROVISIONING_STEP = "queued"


@dataclass(slots=True)
class DomainDetail:
    domain: Domain
    dns_records: list[DomainDnsRecord]


@dataclass(slots=True)
class DomainVerificationResult:
    domain: Domain
    dns_records: list[DomainDnsRecord]
    fully_verified: bool

    @property
    def verified_records(self) -> int:
        return sum(1 for record in self.dns_records if record.verification_status == "verified")

    @property
    def total_records(self) -> int:
        return len(self.dns_records)


@dataclass(slots=True, frozen=True)
class DomainProvisionEnqueueResult:
    domain_id: str
    run_id: str
    status: str


@dataclass(slots=True, frozen=True)
class DomainProvisioningAuditEntry:
    id: str
    domain_id: str
    domain_name: str
    provider: str
    status: str
    reason_code: str | None
    started_at: datetime | None
    completed_at: datetime | None
    steps: list[ProvisioningStep]


@dataclass(slots=True, frozen=True)
class DomainZone:
    id: str
    name: str
    provider: Literal["cloudflare", "route53"]


class DomainService:
    def __init__(
        self,
        settings: Settings,
        *,
        dns_verifier: DNSVerificationAdapter | None = None,
        ses_provisioner: SesDomainProvisioner | None = None,
        dns_secret_provider: AwsSecretsManagerSecretProvider | None = None,
        sleep: Callable[[float], Awaitable[None]] | None = None,
    ) -> None:
        self._settings = settings
        self._session_factory = get_session_factory()
        self._dns_verifier = dns_verifier or DnsPythonVerificationAdapter()
        self._ses_provisioner = ses_provisioner or Boto3SesDomainProvisioner(settings)
        self._dns_secret_provider = dns_secret_provider or AwsSecretsManagerSecretProvider(settings)
        self._sleep = sleep or asyncio.sleep

    async def create_domain(
        self,
        *,
        actor: CurrentActor,
        name: str,
        dns_provider: str,
        parent_domain: str | None,
        ses_region: str,
        default_configuration_set_name: str | None,
        event_destination_sns_topic_arn: str | None,
        ip_address: str | None,
        user_agent: str | None,
        route53_hosted_zone_id: str | None = None,
        cloudflare_zone_id: str | None = None,
    ) -> DomainDetail:
        self._require_admin(actor)

        normalized_name = self._normalize_domain_name(name)
        normalized_parent = self._normalize_domain_name(parent_domain) if parent_domain else None
        if normalized_parent and normalized_parent == normalized_name:
            raise ValidationError("parent_domain cannot be the same as name")

        if dns_provider not in {"cloudflare", "route53", "godaddy", "manual"}:
            raise ValidationError("Unsupported dns_provider")

        config_set_name = default_configuration_set_name or f"{normalized_name}-default"
        mail_from_domain = f"mail.{normalized_name}"
        expected_records = self.build_expected_dns_records(
            domain_name=normalized_name,
            parent_domain=normalized_parent,
            ses_region=ses_region,
            mail_from_domain=mail_from_domain,
        )

        metadata_json = self._build_domain_metadata(
            route53_hosted_zone_id=route53_hosted_zone_id,
            cloudflare_zone_id=cloudflare_zone_id,
        )

        async with UnitOfWork(self._session_factory) as uow:
            repo = DomainRepository(uow.require_session())
            existing = await repo.get_domain_by_name(normalized_name)
            if existing is not None:
                raise ConflictError("A domain with this name already exists")

            configuration_set = await repo.get_configuration_set_by_name(config_set_name)
            if configuration_set is None:
                configuration_set = await repo.create_configuration_set(
                    name=config_set_name,
                    ses_region=ses_region,
                    event_destination_sns_topic_arn=event_destination_sns_topic_arn,
                )

            domain = await repo.create_domain(
                name=normalized_name,
                parent_domain=normalized_parent,
                dns_provider=dns_provider,
                ses_region=ses_region,
                mail_from_domain=mail_from_domain,
                default_configuration_set_id=configuration_set.id,
                rate_limit_per_hour=self._settings.default_domain_hourly_rate_limit,
                metadata_json=metadata_json,
            )
            records = await repo.create_dns_records(domain_id=domain.id, records=expected_records)
            await self._write_audit_log(
                repo=repo,
                actor=actor,
                action="domain.create",
                resource_type="domain",
                resource_id=domain.id,
                after_state={
                    "name": domain.name,
                    "dns_provider": domain.dns_provider,
                    "default_configuration_set_id": domain.default_configuration_set_id,
                    "dns_record_count": len(records),
                },
                ip_address=ip_address,
                user_agent=user_agent,
            )
            return DomainDetail(domain=domain, dns_records=records)

    async def list_domains(self) -> list[DomainDetail]:
        async with self._session_factory() as session:
            repo = DomainRepository(session)
            domains = await repo.list_domains()
            details: list[DomainDetail] = []
            for domain in domains:
                records = await repo.list_dns_records_for_domain(domain.id)
                details.append(DomainDetail(domain=domain, dns_records=records))
            return details

    async def get_domain(self, domain_id: str) -> DomainDetail:
        async with self._session_factory() as session:
            repo = DomainRepository(session)
            domain = await repo.get_domain_by_id(domain_id)
            if domain is None:
                raise NotFoundError("Domain not found")
            records = await repo.list_dns_records_for_domain(domain.id)
            return DomainDetail(domain=domain, dns_records=records)

    async def update_domain_rate_limit(
        self,
        *,
        actor: CurrentActor,
        domain_id: str,
        rate_limit_per_hour: int,
        ip_address: str | None,
        user_agent: str | None,
    ) -> DomainDetail:
        self._require_admin(actor)
        if rate_limit_per_hour < 1:
            raise ValidationError("rate_limit_per_hour must be positive")

        async with UnitOfWork(self._session_factory) as uow:
            repo = DomainRepository(uow.require_session())
            domain = await repo.get_domain_by_id(domain_id)
            if domain is None:
                raise NotFoundError("Domain not found")

            before_rate_limit = domain.rate_limit_per_hour
            await repo.update_domain_fields(
                domain_id=domain.id,
                values={"rate_limit_per_hour": rate_limit_per_hour},
            )
            await self._write_audit_log(
                repo=repo,
                actor=actor,
                action="domain.throttle.update",
                resource_type="domain",
                resource_id=domain.id,
                before_state={"rate_limit_per_hour": before_rate_limit},
                after_state={"rate_limit_per_hour": rate_limit_per_hour},
                ip_address=ip_address,
                user_agent=user_agent,
            )

            refreshed = await repo.get_domain_by_id(domain.id)
            if refreshed is None:
                raise NotFoundError("Domain not found")
            records = await repo.list_dns_records_for_domain(refreshed.id)
            return DomainDetail(domain=refreshed, dns_records=records)

    async def verify_domain(
        self,
        *,
        actor: CurrentActor,
        domain_id: str,
        ip_address: str | None,
        user_agent: str | None,
    ) -> DomainVerificationResult:
        self._require_admin(actor)
        return await self._verify_domain_internal(
            domain_id=domain_id,
            actor_type=actor.actor_type,
            actor_id=actor.user.id,
            ip_address=ip_address,
            user_agent=user_agent,
        )

    async def verify_domain_system(self, domain_id: str) -> DomainVerificationResult:
        return await self._verify_domain_internal(
            domain_id=domain_id,
            actor_type="system",
            actor_id=None,
            ip_address=None,
            user_agent="celery:verify_domain_dns",
        )

    async def enqueue_domain_provisioning(
        self,
        *,
        actor: CurrentActor,
        domain_id: str,
        force: bool,
        ip_address: str | None,
        user_agent: str | None,
    ) -> DomainProvisionEnqueueResult:
        self._require_admin(actor)

        async with UnitOfWork(self._session_factory) as uow:
            repo = DomainRepository(uow.require_session())
            domain = await repo.get_domain_by_id(domain_id)
            if domain is None:
                raise NotFoundError("Domain not found")
            if domain.reputation_status in {"retired", "burnt"}:
                raise ConflictError(
                    f"Domain cannot be provisioned in state {domain.reputation_status}"
                )

            status = self._provisioning_status_from_domain(domain)
            if status.status == "running" and not force:
                raise ConflictError("Domain provisioning is already running")
            if domain.verification_status == "verified" and not force:
                return DomainProvisionEnqueueResult(
                    domain_id=domain.id,
                    run_id=status.run_id or str(uuid4()),
                    status="verified",
                )

            run_id = str(uuid4())
            queued_step = ProvisioningStep(
                name=_DEFAULT_PROVISIONING_STEP,
                status="queued",
                at=datetime.now(UTC),
                message="Provisioning task queued",
            )
            next_status = DomainProvisioningStatus(
                domain_id=domain.id,
                run_id=run_id,
                status="queued",
                reason_code=None,
                started_at=None,
                completed_at=None,
                steps=[queued_step],
            )

            await self._persist_provisioning_state(
                repo=repo,
                domain=domain,
                status=next_status,
                verification_status="pending",
            )
            await AuthRepository(uow.require_session()).write_audit_log(
                actor_type=actor.actor_type,
                actor_id=actor.user.id,
                action="domain.provision.enqueue",
                resource_type="domain",
                resource_id=domain.id,
                after_state=next_status.to_metadata(),
                ip_address=ip_address,
                user_agent=user_agent,
            )
            return DomainProvisionEnqueueResult(
                domain_id=domain.id,
                run_id=run_id,
                status="queued",
            )

    async def get_domain_provisioning_status(self, *, domain_id: str) -> DomainProvisioningStatus:
        async with self._session_factory() as session:
            repo = DomainRepository(session)
            domain = await repo.get_domain_by_id(domain_id)
            if domain is None:
                raise NotFoundError("Domain not found")
            return self._provisioning_status_from_domain(domain)

    async def list_zones_for_provider(
        self,
        *,
        actor: CurrentActor,
        provider: str,
    ) -> list[DomainZone]:
        self._require_admin(actor)
        normalized_provider = provider.strip().lower()
        if normalized_provider == "cloudflare":
            provisioner: DNSProvisioner = CloudflareDNSProvisioner(
                self._settings,
                secret_provider=self._dns_secret_provider,
            )
        elif normalized_provider == "route53":
            provisioner = Route53DNSProvisioner(self._settings)
        else:
            raise ValidationError("provider must be one of: cloudflare, route53")

        zones = await provisioner.list_zones()
        return [
            DomainZone(
                id=zone.id,
                name=zone.name,
                provider=normalized_provider,
            )
            for zone in zones
        ]

    async def list_provisioning_audit(
        self,
        *,
        actor: CurrentActor,
        limit: int = 50,
    ) -> list[DomainProvisioningAuditEntry]:
        self._require_admin(actor)
        bounded_limit = max(1, min(limit, 200))

        async with self._session_factory() as session:
            logs_result = await session.execute(
                select(AuditLog)
                .where(AuditLog.resource_type == "domain")
                .where(
                    AuditLog.action.in_(
                        [
                            "domain.provision.enqueue",
                            "domain.provision.success",
                            "domain.provision.failed",
                        ]
                    )
                )
                .order_by(AuditLog.occurred_at.desc(), AuditLog.id.desc())
                .limit(bounded_limit * 6)
            )
            logs = list(logs_result.scalars().all())
            domain_ids = sorted(
                {
                    str(log.resource_id)
                    for log in logs
                    if log.resource_id
                }
            )

            domains_by_id: dict[str, Domain] = {}
            if domain_ids:
                domains_result = await session.execute(
                    select(Domain).where(Domain.id.in_(domain_ids))
                )
                domains = list(domains_result.scalars().all())
                domains_by_id = {domain.id: domain for domain in domains}

            seen_run_ids: set[str] = set()
            attempts: list[DomainProvisioningAuditEntry] = []
            for log in logs:
                domain_id = str(log.resource_id) if log.resource_id else ""
                if not domain_id:
                    continue
                after_state = log.after_state if isinstance(log.after_state, dict) else None
                status_payload = DomainProvisioningStatus.from_metadata(
                    domain_id=domain_id,
                    payload=after_state,
                )
                run_id = status_payload.run_id or f"audit-{log.id}"
                if run_id in seen_run_ids:
                    continue
                seen_run_ids.add(run_id)

                domain = domains_by_id.get(domain_id)
                attempts.append(
                    DomainProvisioningAuditEntry(
                        id=run_id,
                        domain_id=domain_id,
                        domain_name=domain.name if domain else domain_id,
                        provider=domain.dns_provider if domain else "manual",
                        status=status_payload.status,
                        reason_code=status_payload.reason_code,
                        started_at=status_payload.started_at,
                        completed_at=status_payload.completed_at,
                        steps=status_payload.steps,
                    )
                )
                if len(attempts) >= bounded_limit:
                    break
            return attempts

    async def provision_domain_system(
        self,
        *,
        domain_id: str,
        run_id: str | None,
    ) -> DomainProvisioningStatus:
        active_run_id = run_id or str(uuid4())
        await self._append_provisioning_step(
            domain_id=domain_id,
            run_id=active_run_id,
            step_name="start",
            step_status="running",
            message="Provisioning started",
            set_status="running",
        )

        try:
            domain = await self._get_domain_model(domain_id=domain_id)
            if domain.verification_status == "verified":
                completed = await self._append_provisioning_step(
                    domain_id=domain.id,
                    run_id=active_run_id,
                    step_name="already_verified",
                    step_status="completed",
                    message="Domain is already verified",
                    set_status="verified",
                    mark_complete=True,
                )
                return completed

            dns_provisioner, zone_id = await self._resolve_dns_provisioner(domain=domain)
            ses_state = await self._run_provisioning_step(
                domain_id=domain.id,
                run_id=active_run_id,
                step_name="create_ses_identity",
                step_fn=lambda: self._ses_provisioner.ensure_identity(domain_name=domain.name),
            )

            config_set = await self._ensure_configuration_set_for_domain(domain=domain)
            await self._run_provisioning_step(
                domain_id=domain.id,
                run_id=active_run_id,
                step_name="ensure_configuration_set",
                step_fn=lambda: self._ses_provisioner.ensure_configuration_set(
                    name=config_set.name,
                    sns_topic_arn=config_set.event_destination_sns_topic_arn
                    or self._settings.ses_sns_topic_arn,
                ),
            )

            mail_from_domain = domain.mail_from_domain or f"mail.{domain.name}"
            await self._run_provisioning_step(
                domain_id=domain.id,
                run_id=active_run_id,
                step_name="configure_mail_from",
                step_fn=lambda: self._ses_provisioner.ensure_mail_from(
                    domain_name=domain.name,
                    mail_from_domain=mail_from_domain,
                ),
            )

            expected_records = self.build_expected_dns_records(
                domain_name=domain.name,
                parent_domain=domain.parent_domain,
                ses_region=domain.ses_region,
                mail_from_domain=mail_from_domain,
                dkim_tokens=ses_state.dkim_tokens,
            )
            synced_records = await self._run_provisioning_step(
                domain_id=domain.id,
                run_id=active_run_id,
                step_name="sync_dns_records",
                step_fn=lambda: self._sync_expected_dns_records(
                    domain_id=domain.id,
                    expected_records=expected_records,
                ),
            )

            await self._run_provisioning_step(
                domain_id=domain.id,
                run_id=active_run_id,
                step_name="apply_dns_records",
                step_fn=lambda: self._apply_dns_records_to_provider(
                    domain_id=domain.id,
                    dns_provisioner=dns_provisioner,
                    zone_id=zone_id,
                    records=synced_records,
                ),
            )

            final_identity = await self._run_provisioning_step(
                domain_id=domain.id,
                run_id=active_run_id,
                step_name="poll_ses_verification",
                step_fn=lambda: self._poll_ses_verification(domain_name=domain.name),
            )

            await self._run_provisioning_step(
                domain_id=domain.id,
                run_id=active_run_id,
                step_name="verify_dns_state",
                step_fn=lambda: self._verify_provider_records(
                    dns_provisioner=dns_provisioner,
                    zone_id=zone_id,
                    records=synced_records,
                ),
            )

            async with UnitOfWork(self._session_factory) as uow:
                repo = DomainRepository(uow.require_session())
                current_domain = await repo.get_domain_by_id(domain.id)
                if current_domain is None:
                    raise NotFoundError("Domain not found")

                await repo.update_domain_fields(
                    domain_id=domain.id,
                    values={
                        "verification_status": "verified",
                        "spf_status": "verified",
                        "dkim_status": "verified",
                        "dmarc_status": "verified",
                        "ses_identity_arn": final_identity.identity_arn,
                    },
                )
                refreshed_domain = await repo.get_domain_by_id(domain.id)
                if refreshed_domain is None:
                    raise NotFoundError("Domain not found")

                success_status = await self._append_step_with_repo(
                    repo=repo,
                    domain=refreshed_domain,
                    run_id=active_run_id,
                    step=ProvisioningStep(
                        name="complete",
                        status="completed",
                        at=datetime.now(UTC),
                        message="Domain provisioning completed",
                    ),
                    set_status="verified",
                    mark_complete=True,
                    verification_status="verified",
                )
                await AuthRepository(uow.require_session()).write_audit_log(
                    actor_type="system",
                    actor_id=None,
                    action="domain.provision.success",
                    resource_type="domain",
                    resource_id=domain.id,
                    after_state=success_status.to_metadata(),
                )
                return success_status
        except Exception as exc:
            failure = await self._mark_provisioning_failed(
                domain_id=domain_id,
                run_id=active_run_id,
                exc=exc,
            )
            return failure

    async def retire_domain(
        self,
        *,
        actor: CurrentActor,
        domain_id: str,
        reason: str,
        ip_address: str | None,
        user_agent: str | None,
    ) -> DomainDetail:
        self._require_admin(actor)
        if not reason.strip():
            raise ValidationError("Retirement reason is required")

        async with UnitOfWork(self._session_factory) as uow:
            repo = DomainRepository(uow.require_session())
            domain = await repo.get_domain_by_id(domain_id)
            if domain is None:
                raise NotFoundError("Domain not found")

            await self._cleanup_remote_resources(domain=domain, repo=repo)
            await repo.deactivate_dns_records_except(domain_id=domain.id, keep_record_ids=[])

            retired = await repo.retire_domain(domain_id=domain.id, reason=reason)
            if not retired:
                raise NotFoundError("Domain not found")

            refreshed = await repo.get_domain_by_id(domain.id)
            if refreshed is None:
                raise NotFoundError("Domain not found")

            records = await repo.list_dns_records_for_domain(refreshed.id)
            await self._write_audit_log(
                repo=repo,
                actor=actor,
                action="domain.retire",
                resource_type="domain",
                resource_id=refreshed.id,
                before_state={"reputation_status": domain.reputation_status},
                after_state={"reputation_status": "retired", "reason": reason},
                ip_address=ip_address,
                user_agent=user_agent,
            )
            return DomainDetail(domain=refreshed, dns_records=records)

    async def create_configuration_set(
        self,
        *,
        actor: CurrentActor,
        payload: SESConfigurationSetCreateRequest,
    ) -> SESConfigurationSet:
        self._require_admin(actor)
        async with UnitOfWork(self._session_factory) as uow:
            repo = DomainRepository(uow.require_session())
            existing = await repo.get_configuration_set_by_name(payload.name)
            if existing is not None:
                raise ConflictError("Configuration set name already exists")
            return await repo.create_configuration_set(
                name=payload.name.strip(),
                ses_region=payload.ses_region.strip(),
                event_destination_sns_topic_arn=payload.event_destination_sns_topic_arn,
            )

    async def list_configuration_sets(self) -> list[SESConfigurationSet]:
        async with self._session_factory() as session:
            repo = DomainRepository(session)
            return await repo.list_configuration_sets()

    async def create_ip_pool(self, *, actor: CurrentActor, payload: IPPoolCreateRequest) -> IPPool:
        self._require_admin(actor)
        async with UnitOfWork(self._session_factory) as uow:
            repo = DomainRepository(uow.require_session())
            existing = await repo.get_ip_pool_by_name(payload.name)
            if existing is not None:
                raise ConflictError("IP pool name already exists")
            return await repo.create_ip_pool(
                name=payload.name.strip(),
                ses_pool_name=payload.ses_pool_name.strip(),
                dedicated_ips=[ip.strip() for ip in payload.dedicated_ips if ip.strip()],
                traffic_weight=payload.traffic_weight,
            )

    async def list_ip_pools(self) -> list[IPPool]:
        async with self._session_factory() as session:
            repo = DomainRepository(session)
            return await repo.list_ip_pools()

    def build_expected_dns_records(
        self,
        *,
        domain_name: str,
        parent_domain: str | None,
        ses_region: str,
        mail_from_domain: str,
        dkim_tokens: list[str] | None = None,
    ) -> list[ExpectedDnsRecord]:
        normalized_domain = self._normalize_domain_name(domain_name)
        normalized_parent = (
            self._normalize_domain_name(parent_domain)
            if parent_domain
            else normalized_domain
        )
        normalized_mail_from = self._normalize_domain_name(mail_from_domain)
        normalized_tokens = [item.strip() for item in (dkim_tokens or []) if item.strip()]

        dkim_records: list[ExpectedDnsRecord] = []
        if normalized_tokens:
            for token in normalized_tokens:
                dkim_records.append(
                    ExpectedDnsRecord(
                        record_type=DnsRecordType.CNAME,
                        name=f"{token}._domainkey.{normalized_domain}",
                        value=f"{token}.dkim.amazonses.com",
                        purpose="dkim",
                    )
                )
        else:
            for selector in ("selector1", "selector2", "selector3"):
                dkim_records.append(
                    ExpectedDnsRecord(
                        record_type=DnsRecordType.CNAME,
                        name=f"{selector}._domainkey.{normalized_domain}",
                        value=f"{selector}-{normalized_domain}.dkim.amazonses.com",
                        purpose="dkim",
                    )
                )

        return [
            ExpectedDnsRecord(
                record_type=DnsRecordType.TXT,
                name=normalized_domain,
                value="v=spf1 include:amazonses.com -all",
                purpose="spf",
            ),
            *dkim_records,
            ExpectedDnsRecord(
                record_type=DnsRecordType.TXT,
                name=f"_dmarc.{normalized_domain}",
                value=f"v=DMARC1; p=none; rua=mailto:dmarc@{normalized_parent}",
                purpose="dmarc",
            ),
            ExpectedDnsRecord(
                record_type=DnsRecordType.MX,
                name=normalized_mail_from,
                value=f"feedback-smtp.{ses_region}.amazonses.com",
                purpose="mail_from",
                priority=10,
            ),
            ExpectedDnsRecord(
                record_type=DnsRecordType.TXT,
                name=normalized_mail_from,
                value="v=spf1 include:amazonses.com -all",
                purpose="mail_from",
            ),
        ]

    async def _verify_domain_internal(
        self,
        *,
        domain_id: str,
        actor_type: str,
        actor_id: str | None,
        ip_address: str | None,
        user_agent: str | None,
    ) -> DomainVerificationResult:
        async with UnitOfWork(self._session_factory) as uow:
            repo = DomainRepository(uow.require_session())
            domain = await repo.get_domain_by_id(domain_id)
            if domain is None:
                raise NotFoundError("Domain not found")
            if domain.reputation_status in {"burnt", "retired"}:
                raise ConflictError(
                    f"Domain cannot be verified in state {domain.reputation_status}"
                )

            records = await repo.list_dns_records_for_domain(domain.id)
            if not records:
                raise ValidationError("Domain has no DNS records to verify")

            for record in records:
                verified = await self._verify_dns_record(record)
                await repo.update_dns_record_verification(record_id=record.id, is_verified=verified)

            refreshed_records = await repo.list_dns_records_for_domain(domain.id)
            spf_status = self._purpose_status(refreshed_records, purpose="spf")
            dkim_status = self._purpose_status(refreshed_records, purpose="dkim")
            dmarc_status = self._purpose_status(refreshed_records, purpose="dmarc")
            mail_from_status = self._purpose_status(refreshed_records, purpose="mail_from")
            fully_verified = (
                spf_status == "verified"
                and dkim_status == "verified"
                and dmarc_status == "verified"
                and mail_from_status == "verified"
            )
            verification_status = "verified" if fully_verified else "pending"
            await repo.update_domain_status(
                domain_id=domain.id,
                verification_status=verification_status,
                spf_status=spf_status,
                dkim_status=dkim_status,
                dmarc_status=dmarc_status,
            )

            refreshed_domain = await repo.get_domain_by_id(domain.id)
            if refreshed_domain is None:
                raise NotFoundError("Domain not found")

            await AuthRepository(uow.require_session()).write_audit_log(
                actor_type=actor_type,
                actor_id=actor_id,
                action="domain.verify",
                resource_type="domain",
                resource_id=refreshed_domain.id,
                after_state={
                    "verification_status": refreshed_domain.verification_status,
                    "spf_status": refreshed_domain.spf_status,
                    "dkim_status": refreshed_domain.dkim_status,
                    "dmarc_status": refreshed_domain.dmarc_status,
                    "fully_verified": fully_verified,
                },
                ip_address=ip_address,
                user_agent=user_agent,
            )

            return DomainVerificationResult(
                domain=refreshed_domain,
                dns_records=refreshed_records,
                fully_verified=fully_verified,
            )

    async def _verify_dns_record(self, record: DomainDnsRecord) -> bool:
        record_type = DnsRecordType(record.record_type.upper())
        observed = await self._dns_verifier.lookup(record_type=record_type, name=record.name)
        expected = normalize_dns_value(record.value)
        if record_type is DnsRecordType.MX:
            return any(value.endswith(expected) for value in observed)
        return expected in observed

    async def _resolve_dns_provisioner(self, *, domain: Domain) -> tuple[DNSProvisioner, str]:
        provider = domain.dns_provider
        if provider == "cloudflare":
            provisioner = CloudflareDNSProvisioner(
                self._settings,
                secret_provider=self._dns_secret_provider,
            )
            explicit_zone_id = self._domain_metadata_value(domain, "cloudflare_zone_id")
            if isinstance(explicit_zone_id, str) and explicit_zone_id.strip():
                return provisioner, explicit_zone_id.strip()
            zone_id = await self._resolve_zone_id_from_list(
                provisioner=provisioner,
                preferred_zone_name=domain.parent_domain or domain.name,
                domain_name=domain.name,
            )
            return provisioner, zone_id

        if provider == "route53":
            provisioner = Route53DNSProvisioner(self._settings)
            explicit_zone_id = self._domain_metadata_value(domain, "route53_hosted_zone_id")
            if isinstance(explicit_zone_id, str) and explicit_zone_id.strip():
                return provisioner, explicit_zone_id.strip()
            if self._settings.route53_default_hosted_zone_id:
                return provisioner, self._settings.route53_default_hosted_zone_id.strip()
            zone_id = await self._resolve_zone_id_from_list(
                provisioner=provisioner,
                preferred_zone_name=domain.parent_domain or domain.name,
                domain_name=domain.name,
            )
            return provisioner, zone_id

        raise ValidationError(
            "Automated provisioning supports cloudflare and route53 providers only"
        )

    async def _resolve_zone_id_from_list(
        self,
        *,
        provisioner: DNSProvisioner,
        preferred_zone_name: str,
        domain_name: str,
    ) -> str:
        zones = await provisioner.list_zones()
        normalized_preferred = self._normalize_domain_name(preferred_zone_name)
        normalized_domain_name = self._normalize_domain_name(domain_name)
        candidates = [zone for zone in zones if zone.name == normalized_preferred]
        if candidates:
            return candidates[0].id

        suffix_matches = [
            zone for zone in zones if normalized_domain_name.endswith(zone.name)
        ]
        if suffix_matches:
            suffix_matches.sort(key=lambda item: len(item.name), reverse=True)
            return suffix_matches[0].id
        raise ZoneNotFoundError(f"No DNS zone found for domain {domain_name}")

    async def _ensure_configuration_set_for_domain(self, *, domain: Domain) -> SESConfigurationSet:
        async with UnitOfWork(self._session_factory) as uow:
            repo = DomainRepository(uow.require_session())
            config_set = None
            if domain.default_configuration_set_id:
                config_set = await repo.get_configuration_set_by_id(
                    domain.default_configuration_set_id
                )
            if config_set is None:
                config_set = await repo.create_configuration_set(
                    name=f"{domain.name}-default",
                    ses_region=domain.ses_region,
                    event_destination_sns_topic_arn=self._settings.ses_sns_topic_arn,
                )
                await repo.update_domain_fields(
                    domain_id=domain.id,
                    values={"default_configuration_set_id": config_set.id},
                )
            return config_set

    async def _sync_expected_dns_records(
        self,
        *,
        domain_id: str,
        expected_records: list[ExpectedDnsRecord],
    ) -> list[DomainDnsRecord]:
        async with UnitOfWork(self._session_factory) as uow:
            repo = DomainRepository(uow.require_session())
            keep_ids: list[str] = []
            for expected in expected_records:
                existing = await repo.get_active_dns_record_by_signature(
                    domain_id=domain_id,
                    record_type=expected.record_type.value,
                    name=expected.name,
                    purpose=expected.purpose,
                )
                if existing is None:
                    created = await repo.create_dns_record(
                        domain_id=domain_id,
                        record_type=expected.record_type.value,
                        name=expected.name,
                        value=expected.value,
                        purpose=expected.purpose,
                        priority=expected.priority,
                    )
                    keep_ids.append(created.id)
                    continue

                await repo.update_dns_record(
                    record_id=existing.id,
                    values={
                        "value": expected.value,
                        "priority": expected.priority,
                        "is_active": True,
                        "verification_status": "pending",
                    },
                )
                keep_ids.append(existing.id)

            await repo.deactivate_dns_records_except(
                domain_id=domain_id,
                keep_record_ids=keep_ids,
            )
            return await repo.list_dns_records_for_domain(domain_id)

    async def _apply_dns_records_to_provider(
        self,
        *,
        domain_id: str,
        dns_provisioner: DNSProvisioner,
        zone_id: str,
        records: list[DomainDnsRecord],
    ) -> None:
        provider_ids_by_record_signature: dict[tuple[str, str], str] = {}
        if isinstance(dns_provisioner, Route53DNSProvisioner) and records:
            batch_inputs = [
                DNSRecordInput(
                    record_type=record.record_type,
                    name=record.name,
                    value=record.value,
                    ttl=300,
                    priority=record.priority,
                )
                for record in records
            ]
            batch_provider_ids = await dns_provisioner.upsert_records(
                zone_id=zone_id,
                records=batch_inputs,
            )
            provider_ids_by_record_signature = {
                (
                    input_record.record_type.upper(),
                    normalize_dns_value(input_record.name),
                ): batch_provider_ids[Route53DNSProvisioner._record_id(input_record)]
                for input_record in batch_inputs
            }

        async with UnitOfWork(self._session_factory) as uow:
            repo = DomainRepository(uow.require_session())
            for record in records:
                signature = (record.record_type.upper(), normalize_dns_value(record.name))
                provider_record_id = provider_ids_by_record_signature.get(signature)
                if provider_record_id is None:
                    input_record = DNSRecordInput(
                        record_type=record.record_type,
                        name=record.name,
                        value=record.value,
                        ttl=300,
                        priority=record.priority,
                    )
                    provider_record_id = await dns_provisioner.create_record(
                        zone_id=zone_id,
                        record=input_record,
                    )
                await repo.update_dns_record(
                    record_id=record.id,
                    values={"provider_record_id": provider_record_id},
                )

    async def _verify_provider_records(
        self,
        *,
        dns_provisioner: DNSProvisioner,
        zone_id: str,
        records: list[DomainDnsRecord],
    ) -> None:
        for record in records:
            check = DNSRecordInput(
                record_type=record.record_type,
                name=record.name,
                value=record.value,
                ttl=300,
                priority=record.priority,
            )
            is_valid = await dns_provisioner.verify_record(zone_id=zone_id, record=check)
            if not is_valid:
                raise ExternalServiceError(
                    f"DNS record verification failed for {record.record_type} {record.name}"
                )

    async def _poll_ses_verification(self, *, domain_name: str):
        timeout = timedelta(seconds=self._settings.domain_provisioning_timeout_seconds)
        deadline = datetime.now(UTC) + timeout
        while datetime.now(UTC) < deadline:
            state = await self._ses_provisioner.get_identity_state(domain_name=domain_name)
            if state.verified_for_sending and state.dkim_signing_enabled:
                return state
            await self._sleep(self._settings.domain_provisioning_poll_interval_seconds)
        raise ExternalServiceError("SES identity verification timed out")

    async def _run_provisioning_step[T](
        self,
        *,
        domain_id: str,
        run_id: str,
        step_name: str,
        step_fn: Callable[[], Awaitable[T]],
    ) -> T:
        await self._append_provisioning_step(
            domain_id=domain_id,
            run_id=run_id,
            step_name=step_name,
            step_status="running",
            message=f"{step_name} started",
            set_status="running",
        )
        result = await step_fn()
        await self._append_provisioning_step(
            domain_id=domain_id,
            run_id=run_id,
            step_name=step_name,
            step_status="completed",
            message=f"{step_name} completed",
            set_status="running",
        )
        return result

    async def _append_provisioning_step(
        self,
        *,
        domain_id: str,
        run_id: str,
        step_name: str,
        step_status: str,
        message: str,
        set_status: str,
        mark_complete: bool = False,
    ) -> DomainProvisioningStatus:
        async with UnitOfWork(self._session_factory) as uow:
            repo = DomainRepository(uow.require_session())
            domain = await repo.get_domain_by_id(domain_id)
            if domain is None:
                raise NotFoundError("Domain not found")
            step = ProvisioningStep(
                name=step_name,
                status=step_status,
                at=datetime.now(UTC),
                message=message,
            )
            return await self._append_step_with_repo(
                repo=repo,
                domain=domain,
                run_id=run_id,
                step=step,
                set_status=set_status,
                mark_complete=mark_complete,
            )

    async def _append_step_with_repo(
        self,
        *,
        repo: DomainRepository,
        domain: Domain,
        run_id: str,
        step: ProvisioningStep,
        set_status: str,
        mark_complete: bool,
        verification_status: str | None = None,
        reason_code: str | None = None,
    ) -> DomainProvisioningStatus:
        current_status = self._provisioning_status_from_domain(domain)
        steps = [*current_status.steps, step]
        started_at = current_status.started_at or datetime.now(UTC)
        completed_at = datetime.now(UTC) if mark_complete else None
        next_status = DomainProvisioningStatus(
            domain_id=domain.id,
            run_id=run_id,
            status=set_status if set_status in _PROVISIONING_STATUSES else current_status.status,
            reason_code=reason_code,
            started_at=started_at,
            completed_at=completed_at,
            steps=steps,
        )
        await self._persist_provisioning_state(
            repo=repo,
            domain=domain,
            status=next_status,
            verification_status=verification_status,
        )
        return next_status

    async def _persist_provisioning_state(
        self,
        *,
        repo: DomainRepository,
        domain: Domain,
        status: DomainProvisioningStatus,
        verification_status: str | None = None,
    ) -> None:
        metadata_json = dict(domain.metadata_json or {})
        metadata_json[_PROVISIONING_METADATA_KEY] = status.to_metadata()

        values: dict[str, object] = {"metadata_json": metadata_json}
        if verification_status is not None:
            values["verification_status"] = verification_status
        await repo.update_domain_fields(domain_id=domain.id, values=values)

    async def _mark_provisioning_failed(
        self,
        *,
        domain_id: str,
        run_id: str,
        exc: Exception,
    ) -> DomainProvisioningStatus:
        message = str(exc) or "Domain provisioning failed"
        async with UnitOfWork(self._session_factory) as uow:
            repo = DomainRepository(uow.require_session())
            domain = await repo.get_domain_by_id(domain_id)
            if domain is None:
                raise NotFoundError("Domain not found") from exc
            reason_code = self._resolve_provisioning_failure_reason(
                domain=domain,
                error=exc,
            )

            step = ProvisioningStep(
                name="failed",
                status="failed",
                at=datetime.now(UTC),
                message=message,
            )
            failed_status = await self._append_step_with_repo(
                repo=repo,
                domain=domain,
                run_id=run_id,
                step=step,
                set_status="failed",
                mark_complete=True,
                verification_status="provisioning_failed",
                reason_code=str(reason_code),
            )
            await AuthRepository(uow.require_session()).write_audit_log(
                actor_type="system",
                actor_id=None,
                action="domain.provision.failed",
                resource_type="domain",
                resource_id=domain.id,
                after_state=failed_status.to_metadata(),
            )
            logger.warning(
                "domains.provision.failed",
                domain_id=domain.id,
                reason_code=str(reason_code),
                error=message,
            )
            return failed_status

    @staticmethod
    def _resolve_provisioning_failure_reason(*, domain: Domain, error: Exception) -> str:
        explicit_code = getattr(error, "code", None)
        if isinstance(explicit_code, str) and explicit_code.strip():
            if explicit_code != DomainProvisioningFailureReason.EXTERNAL_SERVICE_ERROR.value:
                return explicit_code

        last_running_step = DomainService._last_running_provisioning_step(domain)
        if last_running_step == "create_ses_identity":
            return DomainProvisioningFailureReason.SES_IDENTITY_SETUP_FAILED.value
        if last_running_step == "ensure_configuration_set":
            return DomainProvisioningFailureReason.SES_CONFIGURATION_SET_FAILED.value
        if last_running_step == "configure_mail_from":
            return DomainProvisioningFailureReason.SES_MAIL_FROM_FAILED.value
        if last_running_step == "sync_dns_records":
            return DomainProvisioningFailureReason.DNS_RECORD_SYNC_FAILED.value
        if last_running_step == "apply_dns_records":
            return DomainProvisioningFailureReason.DNS_RECORD_APPLY_FAILED.value
        if last_running_step == "poll_ses_verification":
            lowered = str(error).lower()
            if "timed out" in lowered or "timeout" in lowered:
                return DomainProvisioningFailureReason.SES_VERIFICATION_TIMEOUT.value
            return DomainProvisioningFailureReason.SES_VERIFICATION_FAILED.value
        if last_running_step == "verify_dns_state":
            return DomainProvisioningFailureReason.DNS_VERIFICATION_FAILED.value

        if isinstance(explicit_code, str) and explicit_code.strip():
            return explicit_code
        return DomainProvisioningFailureReason.DOMAIN_PROVISIONING_FAILED.value

    @staticmethod
    def _last_running_provisioning_step(domain: Domain) -> str | None:
        status = DomainService._provisioning_status_from_domain(domain)
        for step in reversed(status.steps):
            if step.status == "running":
                return step.name
        return None

    async def _cleanup_remote_resources(self, *, domain: Domain, repo: DomainRepository) -> None:
        if domain.dns_provider in {"cloudflare", "route53"}:
            try:
                dns_provisioner, zone_id = await self._resolve_dns_provisioner(domain=domain)
                active_records = await repo.list_dns_records_for_domain(domain.id)
                for record in active_records:
                    if not record.provider_record_id:
                        continue
                    await dns_provisioner.delete_record(
                        zone_id=zone_id,
                        record_id=record.provider_record_id,
                    )
            except Exception as exc:
                logger.warning(
                    "domains.retire.remote_dns_cleanup_failed",
                    domain_id=domain.id,
                    error=str(exc),
                )

        try:
            await self._ses_provisioner.delete_identity(domain_name=domain.name)
        except Exception as exc:
            logger.warning(
                "domains.retire.ses_identity_cleanup_failed",
                domain_id=domain.id,
                error=str(exc),
            )

    async def _get_domain_model(self, *, domain_id: str) -> Domain:
        async with self._session_factory() as session:
            repo = DomainRepository(session)
            domain = await repo.get_domain_by_id(domain_id)
            if domain is None:
                raise NotFoundError("Domain not found")
            return domain

    @staticmethod
    def _purpose_status(records: list[DomainDnsRecord], *, purpose: str) -> str:
        scoped = [record for record in records if record.purpose == purpose and record.is_active]
        if not scoped:
            return "pending"
        if all(record.verification_status == "verified" for record in scoped):
            return "verified"
        return "pending"

    @staticmethod
    def _build_domain_metadata(
        *,
        route53_hosted_zone_id: str | None,
        cloudflare_zone_id: str | None,
    ) -> dict[str, object]:
        metadata: dict[str, object] = {}
        if route53_hosted_zone_id and route53_hosted_zone_id.strip():
            metadata["route53_hosted_zone_id"] = route53_hosted_zone_id.strip()
        if cloudflare_zone_id and cloudflare_zone_id.strip():
            metadata["cloudflare_zone_id"] = cloudflare_zone_id.strip()
        return metadata

    @staticmethod
    def _domain_metadata_value(domain: Domain, key: str) -> object | None:
        metadata = domain.metadata_json
        if not isinstance(metadata, dict):
            return None
        return metadata.get(key)

    @staticmethod
    def _provisioning_status_from_domain(domain: Domain) -> DomainProvisioningStatus:
        metadata = domain.metadata_json if isinstance(domain.metadata_json, dict) else {}
        raw_payload = metadata.get(_PROVISIONING_METADATA_KEY)
        payload = raw_payload if isinstance(raw_payload, dict) else None
        return DomainProvisioningStatus.from_metadata(domain_id=domain.id, payload=payload)

    async def _write_audit_log(
        self,
        *,
        repo: DomainRepository,
        actor: CurrentActor,
        action: str,
        resource_type: str,
        resource_id: str | None,
        after_state: dict[str, object] | None = None,
        before_state: dict[str, object] | None = None,
        ip_address: str | None,
        user_agent: str | None,
    ) -> None:
        await AuthRepository(repo.session).write_audit_log(
            actor_type=actor.actor_type,
            actor_id=actor.user.id,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            after_state=after_state,
            before_state=before_state,
            ip_address=ip_address,
            user_agent=user_agent,
        )

    @staticmethod
    def _normalize_domain_name(value: str | None) -> str:
        if value is None:
            raise ValidationError("Domain name is required")
        normalized = value.strip().lower().rstrip(".")
        if not normalized or "." not in normalized:
            raise ValidationError("Invalid domain format")
        return normalized

    @staticmethod
    def _require_admin(actor: CurrentActor) -> None:
        if actor.user.role != "admin":
            raise PermissionDeniedError("Admin role required")


@lru_cache(maxsize=1)
def get_domain_service() -> DomainService:
    return DomainService(get_settings())


def reset_domain_service_cache() -> None:
    get_domain_service.cache_clear()
