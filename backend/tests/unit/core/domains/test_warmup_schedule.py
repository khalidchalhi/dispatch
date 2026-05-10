from __future__ import annotations

from typing import Any

import pytest

from libs.core.warmup.schemas import (
    custom_warmup_schedule,
    default_warmup_schedule,
)

AuthTestContext = Any


class TestWarmupSchedule:
    def test_default_schedule_has_30_days(self) -> None:
        schedule = default_warmup_schedule()
        assert schedule.total_days() == 30

    def test_default_schedule_day1_is_50(self) -> None:
        schedule = default_warmup_schedule()
        assert schedule.budget_for_day(1) == 50

    def test_default_schedule_day10_is_500(self) -> None:
        schedule = default_warmup_schedule()
        assert schedule.budget_for_day(10) == 500

    def test_default_schedule_day23_is_5000(self) -> None:
        schedule = default_warmup_schedule()
        assert schedule.budget_for_day(23) == 5_000

    def test_day_beyond_schedule_returns_last_volume(self) -> None:
        schedule = default_warmup_schedule()
        last = schedule.volumes[-1]
        assert schedule.budget_for_day(999) == last

    def test_day_zero_returns_zero(self) -> None:
        schedule = default_warmup_schedule()
        assert schedule.budget_for_day(0) == 0

    def test_is_past_schedule_true_after_last_day(self) -> None:
        schedule = default_warmup_schedule()
        assert schedule.is_past_schedule(31) is True

    def test_is_past_schedule_false_on_last_day(self) -> None:
        schedule = default_warmup_schedule()
        assert schedule.is_past_schedule(30) is False


class TestCustomWarmupSchedule:
    def test_returns_correct_volumes(self) -> None:
        schedule = custom_warmup_schedule([100, 500, 1000])
        assert schedule.budget_for_day(1) == 100
        assert schedule.budget_for_day(2) == 500
        assert schedule.budget_for_day(3) == 1000

    def test_empty_volumes_raises(self) -> None:
        with pytest.raises(ValueError, match="must not be empty"):
            custom_warmup_schedule([])

    def test_negative_volume_raises(self) -> None:
        with pytest.raises(ValueError, match="non-negative"):
            custom_warmup_schedule([100, -1, 500])

    def test_clamps_to_last_day_past_schedule(self) -> None:
        schedule = custom_warmup_schedule([100, 200])
        assert schedule.budget_for_day(50) == 200

    def test_total_days_matches_volumes(self) -> None:
        schedule = custom_warmup_schedule([50, 100, 500])
        assert schedule.total_days() == 3


@pytest.mark.asyncio
async def test_daily_cap_allows_within_limit(
    auth_test_context: AuthTestContext,
) -> None:
    from libs.core.throttle.token_bucket import DomainTokenBucket

    bucket = DomainTokenBucket(auth_test_context.settings)
    result = await bucket.try_take_daily(domain_id="domain-abc", daily_limit=5)
    assert result.allowed is True
    assert result.tokens_remaining == 4


@pytest.mark.asyncio
async def test_daily_cap_blocks_when_limit_exceeded(
    auth_test_context: AuthTestContext,
) -> None:
    from libs.core.throttle.token_bucket import DomainTokenBucket

    bucket = DomainTokenBucket(auth_test_context.settings)
    for _ in range(3):
        await bucket.try_take_daily(domain_id="domain-xyz", daily_limit=3)

    result = await bucket.try_take_daily(domain_id="domain-xyz", daily_limit=3)
    assert result.allowed is False
    assert result.tokens_remaining == 0


@pytest.mark.asyncio
async def test_daily_cap_zero_limit_always_allows(
    auth_test_context: AuthTestContext,
) -> None:
    from libs.core.throttle.token_bucket import DomainTokenBucket

    bucket = DomainTokenBucket(auth_test_context.settings)
    result = await bucket.try_take_daily(domain_id="domain-any", daily_limit=0)
    assert result.allowed is True
