from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING
from uuid import uuid4

from sqlalchemy import (
    JSON,
    BigInteger,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from libs.core.db.base import Base

if TYPE_CHECKING:
    from libs.core.sender_profiles.models import SenderProfile


class SESConfigurationSet(Base):
    __tablename__ = "ses_configuration_sets"

    id: Mapped[str] = mapped_column(
        Uuid(as_uuid=False),
        primary_key=True,
        default=lambda: str(uuid4()),
    )
    name: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    ses_region: Mapped[str] = mapped_column(String(32), nullable=False, default="us-east-1")
    reputation_metrics_enabled: Mapped[bool] = mapped_column(nullable=False, default=True)
    sending_enabled: Mapped[bool] = mapped_column(nullable=False, default=True)
    tracking_enabled: Mapped[bool] = mapped_column(nullable=False, default=False)
    event_destination_sns_topic_arn: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    domains: Mapped[list[Domain]] = relationship(back_populates="default_configuration_set")
    sender_profiles: Mapped[list[SenderProfile]] = relationship(back_populates="configuration_set")


class Domain(Base):
    __tablename__ = "domains"

    id: Mapped[str] = mapped_column(
        Uuid(as_uuid=False),
        primary_key=True,
        default=lambda: str(uuid4()),
    )
    name: Mapped[str] = mapped_column(Text, nullable=False, unique=True, index=True)
    parent_domain: Mapped[str | None] = mapped_column(Text, nullable=True)
    dns_provider: Mapped[str] = mapped_column(String(32), nullable=False, default="manual")
    ses_region: Mapped[str] = mapped_column(String(32), nullable=False, default="us-east-1")
    ses_identity_arn: Mapped[str | None] = mapped_column(Text, nullable=True)
    verification_status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    spf_status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    dkim_status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    dmarc_status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    mail_from_domain: Mapped[str | None] = mapped_column(Text, nullable=True)
    custom_tracking_domain: Mapped[str | None] = mapped_column(Text, nullable=True)
    reputation_status: Mapped[str] = mapped_column(String(20), nullable=False, default="warming")
    daily_send_limit: Mapped[int] = mapped_column(Integer, nullable=False, default=50)
    rate_limit_per_hour: Mapped[int] = mapped_column(Integer, nullable=False, default=150)
    lifetime_sends: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    lifetime_bounces: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    lifetime_complaints: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    warmup_stage: Mapped[str] = mapped_column(
        Enum(
            "none",
            "warming",
            "graduated",
            name="domain_warmup_stage",
            native_enum=True,
            validate_strings=True,
        ),
        nullable=False,
        default="none",
    )
    warmup_schedule: Mapped[list[int]] = mapped_column(JSON, nullable=False, default=list)
    warmup_started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    warmup_completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    retired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    retirement_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    metadata_json: Mapped[dict[str, object]] = mapped_column(
        "metadata",
        JSON,
        nullable=False,
        default=dict,
    )
    default_configuration_set_id: Mapped[str | None] = mapped_column(
        Uuid(as_uuid=False),
        ForeignKey("ses_configuration_sets.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    dns_records: Mapped[list[DomainDnsRecord]] = relationship(
        back_populates="domain",
        cascade="all, delete-orphan",
    )
    sender_profiles: Mapped[list[SenderProfile]] = relationship(back_populates="domain")
    default_configuration_set: Mapped[SESConfigurationSet | None] = relationship(
        back_populates="domains",
    )


class DomainDnsRecord(Base):
    __tablename__ = "domain_dns_records"

    id: Mapped[str] = mapped_column(
        Uuid(as_uuid=False),
        primary_key=True,
        default=lambda: str(uuid4()),
    )
    domain_id: Mapped[str] = mapped_column(
        Uuid(as_uuid=False),
        ForeignKey("domains.id", ondelete="CASCADE"),
        nullable=False,
    )
    record_type: Mapped[str] = mapped_column(String(10), nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    value: Mapped[str] = mapped_column(Text, nullable=False)
    priority: Mapped[int | None] = mapped_column(Integer, nullable=True)
    purpose: Mapped[str] = mapped_column(String(40), nullable=False)
    provider_record_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(nullable=False, default=True)
    verification_status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    last_verified_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    domain: Mapped[Domain] = relationship(back_populates="dns_records")


class IPPool(Base):
    __tablename__ = "ip_pools"

    id: Mapped[str] = mapped_column(
        Uuid(as_uuid=False),
        primary_key=True,
        default=lambda: str(uuid4()),
    )
    name: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    ses_pool_name: Mapped[str] = mapped_column(Text, nullable=False)
    dedicated_ips: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    traffic_weight: Mapped[int] = mapped_column(Integer, nullable=False, default=100)
    is_active: Mapped[bool] = mapped_column(nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    sender_profiles: Mapped[list[SenderProfile]] = relationship(back_populates="ip_pool")
