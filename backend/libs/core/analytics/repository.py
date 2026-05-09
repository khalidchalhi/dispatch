from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from uuid import UUID

from sqlalchemy import and_, case, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from libs.core.campaigns.models import Campaign, Message
from libs.core.circuit_breaker.models import CircuitBreakerState
from libs.core.db.session import is_database_ready
from libs.core.domains.models import Domain
from libs.core.events.models import RollingMetric

_ACCOUNT_SCOPE_ID = "00000000-0000-0000-0000-000000000000"

CAMPAIGN_WINDOWS: list[str] = ["1h", "6h", "24h"]
DOMAIN_WINDOWS: list[str] = ["24h", "7d"]
WINDOW_HOURS: dict[str, int] = {"1h": 1, "6h": 6, "24h": 24, "7d": 168}


class AnalyticsRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def database_ready(self) -> bool:
        return await is_database_ready(self.session)

    async def get_campaign(self, *, campaign_id: str) -> Campaign | None:
        return await self.session.get(Campaign, campaign_id)

    async def get_domain(self, *, domain_id: str) -> Domain | None:
        return await self.session.get(Domain, domain_id)

    async def get_rolling_metrics(
        self,
        *,
        scope_type: str,
        scope_id: str,
        windows: list[str],
    ) -> list[RollingMetric]:
        stmt = (
            select(RollingMetric)
            .where(RollingMetric.scope_type == scope_type)
            .where(RollingMetric.scope_id == scope_id)
            .where(RollingMetric.window.in_(windows))
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_circuit_breaker_state(self, *, scope_type: str, scope_id: str) -> str | None:
        stmt = (
            select(CircuitBreakerState.state)
            .where(CircuitBreakerState.scope_type == scope_type)
            .where(CircuitBreakerState.scope_id == scope_id)
        )
        result = await self.session.execute(stmt)
        value = result.scalar_one_or_none()
        if value is None:
            return None
        return str(value)

    async def list_campaign_messages(
        self,
        *,
        campaign_id: str,
        limit: int,
        cursor: tuple[datetime, str] | None,
    ) -> list[Message]:
        stmt = select(Message).where(Message.campaign_id == campaign_id)
        if cursor is not None:
            cur_at_raw, cur_id = cursor
            # Normalize to naive UTC for cross-DB compatibility (SQLite stores naive UTC).
            cur_at = (
                cur_at_raw.replace(tzinfo=None)
                if cur_at_raw.tzinfo is not None
                else cur_at_raw
            )
            cur_uuid = str(UUID(cur_id))
            dialect_name = ""
            bind = self.session.get_bind()
            if bind is not None:
                dialect_name = bind.dialect.name
            if dialect_name == "sqlite":
                # SQLite UUID/date comparisons can behave inconsistently with tied timestamps.
                # Keep ordering in SQL, then apply strict keyset filtering in Python.
                stmt = stmt.where(Message.created_at <= cur_at).order_by(
                    Message.created_at.desc(),
                    Message.id.desc(),
                )
                result = await self.session.execute(stmt)
                rows = list(result.scalars().all())
                filtered: list[Message] = []
                for row in rows:
                    row_created_at = (
                        row.created_at.replace(tzinfo=None)
                        if row.created_at.tzinfo is not None
                        else row.created_at
                    )
                    if row_created_at < cur_at or (
                        row_created_at == cur_at and str(row.id) < cur_uuid
                    ):
                        filtered.append(row)
                    if len(filtered) >= limit + 1:
                        break
                return filtered
            stmt = stmt.where(
                or_(
                    Message.created_at < cur_at,
                    and_(Message.created_at == cur_at, Message.id < cur_uuid),
                )
            )
        # fetch one extra to know whether a next page exists
        stmt = stmt.order_by(Message.created_at.desc(), Message.id.desc()).limit(limit + 1)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_active_campaign_ids(self) -> list[str]:
        stmt = select(Campaign.id).where(
            Campaign.status.in_(["launched", "running", "paused", "completed"])
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_verified_domain_ids(self) -> list[str]:
        stmt = select(Domain.id).where(Domain.verification_status == "verified")
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def aggregate_campaign_window(
        self,
        *,
        campaign_id: str,
        since: datetime,
    ) -> dict[str, int]:
        stmt = select(
            func.sum(case((Message.sent_at >= since, 1), else_=0)).label("sends"),
            func.sum(
                case(
                    (and_(Message.status == "delivered", Message.delivered_at >= since), 1),
                    else_=0,
                )
            ).label("deliveries"),
            func.sum(
                case(
                    (and_(Message.bounce_type.is_not(None), Message.sent_at >= since), 1),
                    else_=0,
                )
            ).label("bounces"),
            func.sum(
                case(
                    (and_(Message.complaint_type.is_not(None), Message.sent_at >= since), 1),
                    else_=0,
                )
            ).label("complaints"),
            func.sum(case((Message.first_opened_at >= since, 1), else_=0)).label("opens"),
            func.sum(case((Message.first_clicked_at >= since, 1), else_=0)).label("clicks"),
            func.sum(case((Message.replied_at >= since, 1), else_=0)).label("replies"),
        ).where(Message.campaign_id == campaign_id)
        row = (await self.session.execute(stmt)).one()
        return {
            "sends": int(row.sends or 0),
            "deliveries": int(row.deliveries or 0),
            "bounces": int(row.bounces or 0),
            "complaints": int(row.complaints or 0),
            "opens": int(row.opens or 0),
            "clicks": int(row.clicks or 0),
            "replies": int(row.replies or 0),
        }

    async def aggregate_domain_window(
        self,
        *,
        domain_id: str,
        since: datetime,
    ) -> dict[str, int]:
        stmt = select(
            func.sum(case((Message.sent_at >= since, 1), else_=0)).label("sends"),
            func.sum(
                case(
                    (and_(Message.status == "delivered", Message.delivered_at >= since), 1),
                    else_=0,
                )
            ).label("deliveries"),
            func.sum(
                case(
                    (and_(Message.bounce_type.is_not(None), Message.sent_at >= since), 1),
                    else_=0,
                )
            ).label("bounces"),
            func.sum(
                case(
                    (and_(Message.complaint_type.is_not(None), Message.sent_at >= since), 1),
                    else_=0,
                )
            ).label("complaints"),
            func.sum(case((Message.first_opened_at >= since, 1), else_=0)).label("opens"),
            func.sum(case((Message.first_clicked_at >= since, 1), else_=0)).label("clicks"),
        ).where(Message.domain_id == domain_id)
        row = (await self.session.execute(stmt)).one()
        return {
            "sends": int(row.sends or 0),
            "deliveries": int(row.deliveries or 0),
            "bounces": int(row.bounces or 0),
            "complaints": int(row.complaints or 0),
            "opens": int(row.opens or 0),
            "clicks": int(row.clicks or 0),
        }

    async def aggregate_account_window(self, *, since: datetime) -> dict[str, int]:
        stmt = select(
            func.sum(case((Message.sent_at >= since, 1), else_=0)).label("sends"),
            func.sum(
                case(
                    (and_(Message.status == "delivered", Message.delivered_at >= since), 1),
                    else_=0,
                )
            ).label("deliveries"),
            func.sum(
                case(
                    (and_(Message.bounce_type.is_not(None), Message.sent_at >= since), 1),
                    else_=0,
                )
            ).label("bounces"),
            func.sum(
                case(
                    (and_(Message.complaint_type.is_not(None), Message.sent_at >= since), 1),
                    else_=0,
                )
            ).label("complaints"),
            func.sum(case((Message.first_opened_at >= since, 1), else_=0)).label("opens"),
            func.sum(case((Message.first_clicked_at >= since, 1), else_=0)).label("clicks"),
        )
        row = (await self.session.execute(stmt)).one()
        return {
            "sends": int(row.sends or 0),
            "deliveries": int(row.deliveries or 0),
            "bounces": int(row.bounces or 0),
            "complaints": int(row.complaints or 0),
            "opens": int(row.opens or 0),
            "clicks": int(row.clicks or 0),
        }

    async def upsert_rolling_metric(
        self,
        *,
        scope_type: str,
        scope_id: str,
        window: str,
        window_end: datetime,
        counts: dict[str, int],
    ) -> None:
        stmt = select(RollingMetric).where(
            RollingMetric.scope_type == scope_type,
            RollingMetric.scope_id == scope_id,
            RollingMetric.window == window,
        )
        result = await self.session.execute(stmt)
        metric = result.scalar_one_or_none()

        sends = counts.get("sends", 0)
        bounces = counts.get("bounces", 0)
        complaints = counts.get("complaints", 0)
        bounce_rate = (
            Decimal(bounces / sends).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
            if sends > 0
            else None
        )
        complaint_rate = (
            Decimal(complaints / sends).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
            if sends > 0
            else None
        )

        if metric is None:
            metric = RollingMetric(
                scope_type=scope_type,
                scope_id=scope_id,
                window=window,
                window_end=window_end,
                sends=sends,
                deliveries=counts.get("deliveries", 0),
                bounces=bounces,
                complaints=complaints,
                opens=counts.get("opens", 0),
                clicks=counts.get("clicks", 0),
                replies=counts.get("replies", 0),
                unsubscribes=counts.get("unsubscribes", 0),
                bounce_rate=bounce_rate,
                complaint_rate=complaint_rate,
                updated_at=datetime.now(UTC),
            )
            self.session.add(metric)
        else:
            metric.window_end = window_end
            metric.sends = sends
            metric.deliveries = counts.get("deliveries", 0)
            metric.bounces = bounces
            metric.complaints = complaints
            metric.opens = counts.get("opens", 0)
            metric.clicks = counts.get("clicks", 0)
            metric.replies = counts.get("replies", 0)
            metric.unsubscribes = counts.get("unsubscribes", 0)
            metric.bounce_rate = bounce_rate
            metric.complaint_rate = complaint_rate
            metric.updated_at = datetime.now(UTC)

        await self.session.flush()

    async def list_top_campaigns_by_sends_today(
        self, *, limit: int
    ) -> list[tuple[Campaign, int]]:
        today_start = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
        subq = (
            select(
                Message.campaign_id,
                func.sum(case((Message.sent_at >= today_start, 1), else_=0)).label("sends_today"),
            )
            .where(Message.campaign_id.is_not(None))
            .group_by(Message.campaign_id)
            .order_by(func.sum(case((Message.sent_at >= today_start, 1), else_=0)).desc())
            .limit(limit)
            .subquery()
        )
        stmt = select(Campaign, subq.c.sends_today).join(
            subq, Campaign.id == subq.c.campaign_id
        )
        result = await self.session.execute(stmt)
        return [(row.Campaign, int(row.sends_today or 0)) for row in result.all()]

    async def list_top_failing_domains(
        self, *, window: str, limit: int
    ) -> list[tuple[Domain, RollingMetric | None]]:
        metric_subq = (
            select(RollingMetric.scope_id)
            .where(RollingMetric.scope_type == "domain")
            .where(RollingMetric.window == window)
            .where(RollingMetric.sends > 0)
            .order_by(RollingMetric.bounce_rate.desc().nulls_last())
            .limit(limit)
            .subquery()
        )
        stmt = (
            select(Domain, RollingMetric)
            .join(metric_subq, Domain.id == metric_subq.c.scope_id)
            .outerjoin(
                RollingMetric,
                and_(
                    RollingMetric.scope_type == "domain",
                    RollingMetric.scope_id == Domain.id,
                    RollingMetric.window == window,
                ),
            )
        )
        result = await self.session.execute(stmt)
        return [(row.Domain, row.RollingMetric) for row in result.all()]

    async def count_sends_in_window(self, *, since: datetime) -> int:
        stmt = select(
            func.sum(case((Message.sent_at >= since, 1), else_=0))
        )
        result = await self.session.execute(stmt)
        return int(result.scalar() or 0)

    @staticmethod
    def window_start(window: str) -> datetime:
        hours = WINDOW_HOURS[window]
        return datetime.now(UTC) - timedelta(hours=hours)
