from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from libs.core.campaigns.models import Message
from libs.core.domains.models import Domain
from libs.core.events.models import RollingMetric


class WarmupRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list_warming_domains(self) -> list[Domain]:
        stmt = select(Domain).where(Domain.warmup_stage == "warming")
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_domain(self, *, domain_id: str) -> Domain | None:
        stmt = select(Domain).where(Domain.id == domain_id)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def update_domain_warmup(
        self,
        *,
        domain_id: str,
        values: dict[str, object],
    ) -> None:
        stmt = (
            update(Domain)
            .where(Domain.id == domain_id)
            .values(**values)
            .execution_options(synchronize_session="fetch")
        )
        await self.session.execute(stmt)

    async def get_24h_rolling_metric(self, *, domain_id: str) -> RollingMetric | None:
        stmt = (
            select(RollingMetric)
            .where(RollingMetric.scope_type == "domain")
            .where(RollingMetric.scope_id == domain_id)
            .where(RollingMetric.window == "24h")
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def count_sent_today(self, *, domain_id: str) -> int:
        day_start = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
        stmt = (
            select(func.count(Message.id))
            .where(Message.domain_id == domain_id)
            .where(Message.sent_at.is_not(None))
            .where(Message.sent_at >= day_start)
        )
        result = await self.session.execute(stmt)
        return int(result.scalar_one() or 0)

    @staticmethod
    def warmup_day_number(warmup_started_at: datetime) -> int:
        """Return 1-based day number of the current warmup.

        Treats naive datetimes as UTC (SQLite returns naive values for tz-aware columns).
        """
        started = (
            warmup_started_at
            if warmup_started_at.tzinfo is not None
            else warmup_started_at.replace(tzinfo=UTC)
        )
        delta = datetime.now(UTC) - started
        return max(1, delta.days + 1)
