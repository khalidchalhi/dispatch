from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from libs.core.circuit_breaker.models import AnomalyAlert, CircuitBreakerState
from libs.core.domains.models import Domain, IPPool
from libs.core.events.models import RollingMetric
from libs.core.sender_profiles.models import SenderProfile

_ACCOUNT_SCOPE_ID = "00000000-0000-0000-0000-000000000000"


class CircuitBreakerRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_state(self, *, scope_type: str, scope_id: str) -> CircuitBreakerState | None:
        normalized_scope_id = str(scope_id).strip()
        stmt = (
            select(CircuitBreakerState)
            .where(CircuitBreakerState.scope_type == scope_type)
            .where(CircuitBreakerState.scope_id == normalized_scope_id)
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def upsert_state(
        self,
        *,
        scope_type: str,
        scope_id: str,
        state: str,
        bounce_rate_24h: Decimal | None,
        complaint_rate_24h: Decimal | None,
        tripped_reason: str | None,
        tripped_at: datetime | None,
        auto_reset_at: datetime | None,
        reset_by: str | None,
        reset_at: datetime | None,
    ) -> CircuitBreakerState:
        normalized_scope_id = str(scope_id).strip()
        row = await self.get_state(scope_type=scope_type, scope_id=normalized_scope_id)
        now = datetime.now(UTC)
        if row is None:
            row = CircuitBreakerState(
                scope_type=scope_type,
                scope_id=normalized_scope_id,
                state=state,
                bounce_rate_24h=bounce_rate_24h,
                complaint_rate_24h=complaint_rate_24h,
                tripped_reason=tripped_reason,
                tripped_at=tripped_at,
                auto_reset_at=auto_reset_at,
                reset_by=reset_by,
                reset_at=reset_at,
                updated_at=now,
            )
            self.session.add(row)
            await self.session.flush()
            return row

        row.state = state
        row.bounce_rate_24h = bounce_rate_24h
        row.complaint_rate_24h = complaint_rate_24h
        row.tripped_reason = tripped_reason
        row.tripped_at = tripped_at
        row.auto_reset_at = auto_reset_at
        row.reset_by = reset_by
        row.reset_at = reset_at
        row.updated_at = now
        await self.session.flush()
        return row

    async def list_states(self) -> list[CircuitBreakerState]:
        stmt = select(CircuitBreakerState).order_by(
            CircuitBreakerState.scope_type.asc(),
            CircuitBreakerState.scope_id.asc(),
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_rolling_metric_24h(
        self,
        *,
        scope_type: str,
        scope_id: str,
    ) -> RollingMetric | None:
        normalized_scope_id = str(scope_id).strip()
        stmt = (
            select(RollingMetric)
            .where(RollingMetric.scope_type == scope_type)
            .where(RollingMetric.scope_id == normalized_scope_id)
            .where(RollingMetric.window == "24h")
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def create_anomaly_alert(
        self,
        *,
        scope_type: str,
        scope_id: str,
        metric: str,
        severity: str,
        message: str,
        observed_value: Decimal | None,
        expected_value: Decimal | None,
    ) -> AnomalyAlert:
        normalized_scope_id = str(scope_id).strip()
        row = AnomalyAlert(
            scope_type=scope_type,
            scope_id=normalized_scope_id,
            metric=metric,
            severity=severity,
            message=message,
            observed_value=observed_value,
            expected_value=expected_value,
        )
        self.session.add(row)
        await self.session.flush()
        return row

    async def list_scope_ids(self, *, scope_type: str) -> list[str]:
        if scope_type == "domain":
            stmt = (
                select(Domain.id)
                .where(Domain.verification_status == "verified")
                .where(Domain.reputation_status.notin_(["retired", "burnt"]))
            )
            result = await self.session.execute(stmt)
            return [str(item) for item in result.scalars().all()]

        if scope_type == "sender_profile":
            stmt = select(SenderProfile.id).where(SenderProfile.is_active.is_(True))
            result = await self.session.execute(stmt)
            return [str(item) for item in result.scalars().all()]

        if scope_type == "ip_pool":
            stmt = select(IPPool.id).where(IPPool.is_active.is_(True))
            result = await self.session.execute(stmt)
            return [str(item) for item in result.scalars().all()]

        if scope_type == "account":
            return [_ACCOUNT_SCOPE_ID]

        return []

    async def list_scope_entities(self, *, scope_type: str) -> list[tuple[str, str]]:
        if scope_type == "domain":
            stmt = (
                select(Domain.id, Domain.name)
                .where(Domain.verification_status == "verified")
                .where(Domain.reputation_status.notin_(["retired", "burnt"]))
                .order_by(Domain.name.asc())
            )
            result = await self.session.execute(stmt)
            return [(str(row[0]), str(row[1])) for row in result.all()]

        if scope_type == "sender_profile":
            stmt = (
                select(SenderProfile.id, SenderProfile.from_email)
                .where(SenderProfile.is_active.is_(True))
                .order_by(SenderProfile.from_email.asc())
            )
            result = await self.session.execute(stmt)
            return [(str(row[0]), str(row[1])) for row in result.all()]

        if scope_type == "ip_pool":
            stmt = (
                select(IPPool.id, IPPool.name)
                .where(IPPool.is_active.is_(True))
                .order_by(IPPool.name.asc())
            )
            result = await self.session.execute(stmt)
            return [(str(row[0]), str(row[1])) for row in result.all()]

        if scope_type == "account":
            return [(_ACCOUNT_SCOPE_ID, "Platform account")]

        return []
