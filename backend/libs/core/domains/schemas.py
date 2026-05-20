from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Literal, cast

from pydantic import BaseModel, Field

from libs.core.domains.models import Domain, DomainDnsRecord, IPPool, SESConfigurationSet

DomainProvider = Literal["cloudflare", "route53", "godaddy", "manual"]
DomainVerificationStatus = Literal[
    "pending",
    "verified",
    "failed",
    "disabled",
    "provisioning_failed",
]
DnsRecordVerificationStatus = Literal["pending", "verified", "failed"]
DomainReputationStatus = Literal["warming", "healthy", "cooling", "burnt", "retired"]
DomainWarmupStage = Literal["none", "warming", "graduated"]


class DnsRecordType(StrEnum):
    TXT = "TXT"
    CNAME = "CNAME"
    MX = "MX"
    A = "A"
    PTR = "PTR"


class DomainCreateRequest(BaseModel):
    name: str = Field(min_length=3, max_length=255)
    dns_provider: DomainProvider = "manual"
    parent_domain: str | None = None
    ses_region: str = "us-east-1"
    default_configuration_set_name: str | None = None
    event_destination_sns_topic_arn: str | None = None
    route53_hosted_zone_id: str | None = None
    cloudflare_zone_id: str | None = None


class DomainProvisionRequest(BaseModel):
    force: bool = False


class DomainRetireRequest(BaseModel):
    reason: str = Field(min_length=3, max_length=500)


class DomainThrottleUpdateRequest(BaseModel):
    rate_limit_per_hour: int = Field(ge=1, le=1_000_000)


class DomainWarmupExtendRequest(BaseModel):
    days: int = Field(ge=1, le=180)


class DomainDnsRecordResponse(BaseModel):
    id: str
    record_type: str
    name: str
    value: str
    priority: int | None
    purpose: str
    is_active: bool
    verification_status: DnsRecordVerificationStatus
    last_verified_at: datetime | None
    created_at: datetime

    @classmethod
    def from_model(cls, record: DomainDnsRecord) -> DomainDnsRecordResponse:
        return cls(
            id=record.id,
            record_type=record.record_type,
            name=record.name,
            value=record.value,
            priority=record.priority,
            purpose=record.purpose,
            is_active=record.is_active,
            verification_status=cast(
                DnsRecordVerificationStatus,
                record.verification_status,
            ),
            last_verified_at=record.last_verified_at,
            created_at=record.created_at,
        )


class DomainResponse(BaseModel):
    id: str
    name: str
    parent_domain: str | None
    dns_provider: DomainProvider
    ses_region: str
    ses_identity_arn: str | None
    verification_status: DomainVerificationStatus
    spf_status: str
    dkim_status: str
    dmarc_status: str
    mail_from_domain: str | None
    custom_tracking_domain: str | None
    reputation_status: DomainReputationStatus
    daily_send_limit: int
    rate_limit_per_hour: int
    retired_at: datetime | None
    retirement_reason: str | None
    default_configuration_set_id: str | None
    created_at: datetime
    updated_at: datetime
    dns_records: list[DomainDnsRecordResponse] = Field(default_factory=list)

    @classmethod
    def from_model(
        cls,
        domain: Domain,
        *,
        dns_records: list[DomainDnsRecord] | None = None,
    ) -> DomainResponse:
        return cls(
            id=domain.id,
            name=domain.name,
            parent_domain=domain.parent_domain,
            dns_provider=cast(DomainProvider, domain.dns_provider),
            ses_region=domain.ses_region,
            ses_identity_arn=domain.ses_identity_arn,
            verification_status=cast(
                DomainVerificationStatus,
                domain.verification_status,
            ),
            spf_status=domain.spf_status,
            dkim_status=domain.dkim_status,
            dmarc_status=domain.dmarc_status,
            mail_from_domain=domain.mail_from_domain,
            custom_tracking_domain=domain.custom_tracking_domain,
            reputation_status=cast(DomainReputationStatus, domain.reputation_status),
            daily_send_limit=domain.daily_send_limit,
            rate_limit_per_hour=domain.rate_limit_per_hour,
            retired_at=domain.retired_at,
            retirement_reason=domain.retirement_reason,
            default_configuration_set_id=domain.default_configuration_set_id,
            created_at=domain.created_at,
            updated_at=domain.updated_at,
            dns_records=[
                DomainDnsRecordResponse.from_model(record)
                for record in (dns_records or [])
            ],
        )


class DomainListResponse(BaseModel):
    items: list[DomainResponse]


class DomainVerifyResponse(BaseModel):
    domain: DomainResponse
    fully_verified: bool
    verified_records: int
    total_records: int


class DomainProvisioningStepResponse(BaseModel):
    name: str
    status: str
    at: datetime
    message: str | None = None


class DomainProvisioningStatusResponse(BaseModel):
    domain_id: str
    run_id: str | None = None
    status: str = "not_started"
    reason_code: str | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    steps: list[DomainProvisioningStepResponse] = Field(default_factory=list)


class DomainProvisionEnqueueResponse(BaseModel):
    domain_id: str
    run_id: str
    status: str


class DomainZoneResponse(BaseModel):
    id: str
    name: str
    provider: Literal["cloudflare", "route53"]


class DomainZoneListResponse(BaseModel):
    items: list[DomainZoneResponse]


class DomainProvisioningAuditItemResponse(BaseModel):
    id: str
    domain_id: str
    domain_name: str
    provider: DomainProvider
    status: str
    reason_code: str | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    steps: list[DomainProvisioningStepResponse] = Field(default_factory=list)


class DomainProvisioningAuditListResponse(BaseModel):
    items: list[DomainProvisioningAuditItemResponse]


class DomainWarmupDayResponse(BaseModel):
    day: int
    cap: int
    actual_sends: int | None = None


class DomainWarmupScheduleResponse(BaseModel):
    total_days: int
    days: list[DomainWarmupDayResponse] = Field(default_factory=list)


class DomainWarmupStatusResponse(BaseModel):
    domain_id: str
    warmup_stage: DomainWarmupStage
    current_day: int
    total_days: int
    today_cap: int
    today_sends: int
    scheduled_graduation_at: datetime | None = None
    graduated_at: datetime | None = None
    warmup_completed_at: datetime | None = None
    schedule: DomainWarmupScheduleResponse


class SESConfigurationSetCreateRequest(BaseModel):
    name: str = Field(min_length=3, max_length=200)
    ses_region: str = "us-east-1"
    event_destination_sns_topic_arn: str | None = None


class SESConfigurationSetResponse(BaseModel):
    id: str
    name: str
    ses_region: str
    reputation_metrics_enabled: bool
    sending_enabled: bool
    tracking_enabled: bool
    event_destination_sns_topic_arn: str | None
    created_at: datetime

    @classmethod
    def from_model(cls, configuration_set: SESConfigurationSet) -> SESConfigurationSetResponse:
        return cls(
            id=configuration_set.id,
            name=configuration_set.name,
            ses_region=configuration_set.ses_region,
            reputation_metrics_enabled=configuration_set.reputation_metrics_enabled,
            sending_enabled=configuration_set.sending_enabled,
            tracking_enabled=configuration_set.tracking_enabled,
            event_destination_sns_topic_arn=configuration_set.event_destination_sns_topic_arn,
            created_at=configuration_set.created_at,
        )


class IPPoolCreateRequest(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    ses_pool_name: str = Field(min_length=2, max_length=120)
    dedicated_ips: list[str] = Field(default_factory=list)
    traffic_weight: int = Field(default=100, ge=1, le=1000)


class IPPoolResponse(BaseModel):
    id: str
    name: str
    ses_pool_name: str
    dedicated_ips: list[str]
    traffic_weight: int
    is_active: bool
    created_at: datetime

    @classmethod
    def from_model(cls, pool: IPPool) -> IPPoolResponse:
        return cls(
            id=pool.id,
            name=pool.name,
            ses_pool_name=pool.ses_pool_name,
            dedicated_ips=list(pool.dedicated_ips),
            traffic_weight=pool.traffic_weight,
            is_active=pool.is_active,
            created_at=pool.created_at,
        )


class ExpectedDnsRecord(BaseModel):
    record_type: DnsRecordType
    name: str
    value: str
    purpose: str
    priority: int | None = None
