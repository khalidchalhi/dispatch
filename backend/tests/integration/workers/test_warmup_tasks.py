from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

import pytest

from libs.core.campaigns.models import Campaign, CampaignRun, Message, SendBatch
from libs.core.campaigns.service import get_campaign_service, reset_campaign_service_cache
from libs.core.db.uow import UnitOfWork
from libs.core.domains.models import Domain
from libs.core.sender_profiles.models import SenderProfile
from libs.core.throttle.token_bucket import DomainTokenBucket, get_domain_token_bucket
from libs.core.warmup.repository import WarmupRepository
from libs.core.warmup.service import WarmupService, reset_warmup_service_cache

AuthTestContext = Any


async def _seed_warming_domain(
    ctx: AuthTestContext,
    *,
    warmup_schedule: list[int],
    warmup_started_at: datetime,
    daily_send_limit: int = 0,
) -> Domain:
    unique = uuid4().hex[:8]
    async with UnitOfWork(ctx.session_factory) as uow:
        domain = Domain(
            name=f"warm-{unique}.dispatch.test",
            verification_status="verified",
            reputation_status="warming",
            warmup_stage="warming",
            warmup_schedule=warmup_schedule,
            warmup_started_at=warmup_started_at,
            daily_send_limit=daily_send_limit,
        )
        uow.require_session().add(domain)
        await uow.require_session().flush()
        return domain


@pytest.mark.asyncio
async def test_compute_daily_budgets_updates_day1_limit(
    auth_test_context: AuthTestContext,
) -> None:
    schedule = [50, 100, 500, 1000]
    now = datetime.now(UTC)
    domain = await _seed_warming_domain(
        auth_test_context,
        warmup_schedule=schedule,
        warmup_started_at=now,
    )
    service = WarmupService(auth_test_context.settings)
    result = await service.compute_daily_budgets()

    assert result["domains_updated"] >= 1

    async with auth_test_context.session_factory() as session:
        repo = WarmupRepository(session)
        refreshed = await repo.get_domain(domain_id=domain.id)

    assert refreshed is not None
    assert refreshed.daily_send_limit == 50


@pytest.mark.asyncio
async def test_compute_daily_budgets_day3_limit(
    auth_test_context: AuthTestContext,
) -> None:
    schedule = [50, 100, 500, 1000]
    two_days_ago = datetime.now(UTC) - timedelta(days=2)
    domain = await _seed_warming_domain(
        auth_test_context,
        warmup_schedule=schedule,
        warmup_started_at=two_days_ago,
    )
    service = WarmupService(auth_test_context.settings)
    await service.compute_daily_budgets()

    async with auth_test_context.session_factory() as session:
        repo = WarmupRepository(session)
        refreshed = await repo.get_domain(domain_id=domain.id)

    assert refreshed is not None
    assert refreshed.daily_send_limit == 500


@pytest.mark.asyncio
async def test_warming_domain_day3_cap_enforced_by_token_bucket(
    auth_test_context: AuthTestContext,
) -> None:
    """Integration test: warming domain at day 3 cannot exceed the day-3 cap."""
    schedule = [50, 100, 5]
    two_days_ago = datetime.now(UTC) - timedelta(days=2)
    domain = await _seed_warming_domain(
        auth_test_context,
        warmup_schedule=schedule,
        warmup_started_at=two_days_ago,
        daily_send_limit=5,
    )

    bucket = DomainTokenBucket(auth_test_context.settings)
    allowed = 0
    blocked = 0
    for _ in range(8):
        decision = await bucket.try_take_daily(
            domain_id=domain.id, daily_limit=domain.daily_send_limit
        )
        if decision.allowed:
            allowed += 1
        else:
            blocked += 1

    assert allowed == 5
    assert blocked == 3


@pytest.mark.asyncio
async def test_compute_daily_budgets_writes_redis_override_for_daily_cap(
    auth_test_context: AuthTestContext,
) -> None:
    schedule = [5]
    now = datetime.now(UTC)
    domain = await _seed_warming_domain(
        auth_test_context,
        warmup_schedule=schedule,
        warmup_started_at=now,
        daily_send_limit=999,  # stale DB value should be ignored by Redis override
    )

    service = WarmupService(auth_test_context.settings)
    bucket = get_domain_token_bucket()
    bucket.reset_daily_counters()
    await service.compute_daily_budgets()

    allowed = 0
    denied = 0
    for _ in range(8):
        decision = await bucket.try_take_daily(domain_id=domain.id, daily_limit=999)
        if decision.allowed:
            allowed += 1
        else:
            denied += 1

    assert allowed == 5
    assert denied == 3


@pytest.mark.asyncio
async def test_graduation_marks_domain_after_schedule(
    auth_test_context: AuthTestContext,
) -> None:
    from libs.core.warmup.schemas import GRADUATION_CLEAN_DAYS

    schedule = [50, 100]
    days_past = 2 + GRADUATION_CLEAN_DAYS
    started = datetime.now(UTC) - timedelta(days=days_past)
    domain = await _seed_warming_domain(
        auth_test_context,
        warmup_schedule=schedule,
        warmup_started_at=started,
    )

    service = WarmupService(auth_test_context.settings)
    result = {"graduated": 0}
    for _ in range(GRADUATION_CLEAN_DAYS):
        result = await service.check_graduation()

    assert result["graduated"] >= 1

    async with auth_test_context.session_factory() as session:
        repo = WarmupRepository(session)
        refreshed = await repo.get_domain(domain_id=domain.id)

    assert refreshed is not None
    assert refreshed.warmup_stage == "graduated"
    assert refreshed.warmup_completed_at is not None
    assert refreshed.daily_send_limit == 0


@pytest.mark.asyncio
async def test_start_warmup_sets_stage_and_budget(
    auth_test_context: AuthTestContext,
) -> None:
    unique = uuid4().hex[:8]
    async with UnitOfWork(auth_test_context.session_factory) as uow:
        domain = Domain(
            name=f"prewarm-{unique}.dispatch.test",
            verification_status="verified",
            reputation_status="warming",
        )
        uow.require_session().add(domain)
        await uow.require_session().flush()
        domain_id = domain.id

    service = WarmupService(auth_test_context.settings)
    updated = await service.start_warmup(domain_id=domain_id, schedule_volumes=[100, 500, 1000])

    assert updated.warmup_stage == "warming"
    assert updated.daily_send_limit == 100
    assert updated.warmup_started_at is not None
    assert updated.warmup_schedule == [100, 500, 1000]
