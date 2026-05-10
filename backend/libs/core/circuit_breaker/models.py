from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from uuid import uuid4

from sqlalchemy import DateTime, ForeignKey, Numeric, String, Text, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column

from libs.core.db.base import Base


class CircuitBreakerState(Base):
    __tablename__ = "circuit_breaker_state"

    id: Mapped[str] = mapped_column(
        Uuid(as_uuid=False),
        primary_key=True,
        default=lambda: str(uuid4()),
    )
    scope_type: Mapped[str] = mapped_column(String(30), nullable=False)
    scope_id: Mapped[str] = mapped_column(Uuid(as_uuid=False), nullable=False)
    state: Mapped[str] = mapped_column(String(20), nullable=False, default="closed")
    bounce_rate_24h: Mapped[Decimal | None] = mapped_column(Numeric(5, 4), nullable=True)
    complaint_rate_24h: Mapped[Decimal | None] = mapped_column(Numeric(5, 4), nullable=True)
    tripped_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    tripped_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    auto_reset_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reset_by: Mapped[str | None] = mapped_column(
        Uuid(as_uuid=False),
        ForeignKey("users.id"),
        nullable=True,
    )
    reset_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )


class AnomalyAlert(Base):
    __tablename__ = "anomaly_alerts"

    id: Mapped[str] = mapped_column(
        Uuid(as_uuid=False),
        primary_key=True,
        default=lambda: str(uuid4()),
    )
    scope_type: Mapped[str] = mapped_column(Text, nullable=False)
    scope_id: Mapped[str] = mapped_column(Uuid(as_uuid=False), nullable=False)
    metric: Mapped[str] = mapped_column(Text, nullable=False)
    severity: Mapped[str] = mapped_column(String(20), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    observed_value: Mapped[Decimal | None] = mapped_column(Numeric, nullable=True)
    expected_value: Mapped[Decimal | None] = mapped_column(Numeric, nullable=True)
    acknowledged_by: Mapped[str | None] = mapped_column(
        Uuid(as_uuid=False),
        ForeignKey("users.id"),
        nullable=True,
    )
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
