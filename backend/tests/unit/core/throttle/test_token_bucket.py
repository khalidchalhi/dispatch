from __future__ import annotations

from dataclasses import dataclass

import pytest

from libs.core.config import Settings
from libs.core.throttle.token_bucket import (
    DomainTokenBucket,
    InMemoryTokenBucketMetricsRecorder,
    TokenBucketMetricsStore,
)


@dataclass(slots=True)
class _Clock:
    current: float = 0.0

    def now(self) -> float:
        return self.current

    def advance(self, seconds: float) -> None:
        self.current += seconds


class _FailingRedisClient:
    async def script_load(self, script: str) -> str:
        _ = script
        raise RuntimeError("redis unavailable")

    async def evalsha(self, sha: str, numkeys: int, *keys_and_args: object) -> object:
        _ = (sha, numkeys, keys_and_args)
        raise RuntimeError("redis unavailable")


@pytest.mark.asyncio
async def test_token_bucket_fallback_limits_and_refills() -> None:
    settings = Settings(app_env="test")
    metrics = InMemoryTokenBucketMetricsRecorder()
    clock = _Clock()
    bucket = DomainTokenBucket(settings, metrics=metrics, now_seconds=clock.now)

    first = await bucket.try_take(domain_id="domain-a", capacity_per_hour=1)
    second = await bucket.try_take(domain_id="domain-a", capacity_per_hour=1)

    assert first.allowed is True
    assert second.allowed is False
    assert second.retry_after_seconds == 3600

    clock.advance(3600)
    third = await bucket.try_take(domain_id="domain-a", capacity_per_hour=1)
    assert third.allowed is True

    assert metrics.events[0].allowed is True
    assert metrics.events[1].allowed is False


@pytest.mark.asyncio
async def test_token_bucket_isolated_per_domain() -> None:
    settings = Settings(app_env="test")
    bucket = DomainTokenBucket(settings)

    first_a = await bucket.try_take(domain_id="domain-a", capacity_per_hour=1)
    first_b = await bucket.try_take(domain_id="domain-b", capacity_per_hour=1)
    second_a = await bucket.try_take(domain_id="domain-a", capacity_per_hour=1)

    assert first_a.allowed is True
    assert first_b.allowed is True
    assert second_a.allowed is False


@pytest.mark.asyncio
async def test_token_bucket_fail_closed_when_redis_unavailable() -> None:
    settings = Settings(
        app_env="local",
        throttle_fail_closed_retry_seconds=45,
    )
    bucket = DomainTokenBucket(settings, redis_client=_FailingRedisClient())

    decision = await bucket.try_take(domain_id="domain-a", capacity_per_hour=10)

    assert decision.allowed is False
    assert decision.retry_after_seconds == 45


@pytest.mark.asyncio
async def test_token_bucket_metrics_store_tracks_tokens_and_denials() -> None:
    settings = Settings(app_env="test")
    metrics = TokenBucketMetricsStore(window_seconds=60)
    clock = _Clock()
    bucket = DomainTokenBucket(settings, metrics=metrics, now_seconds=clock.now)

    await bucket.try_take(domain_id="domain-metrics", capacity_per_hour=1)
    await bucket.try_take(domain_id="domain-metrics", capacity_per_hour=1)

    snapshot = metrics.snapshot("domain-metrics")
    assert snapshot.domain_id == "domain-metrics"
    assert snapshot.tokens_available == 0
    assert snapshot.denials_last_minute == 1
    assert snapshot.denial_rate_per_minute == 1.0
    assert snapshot.total_allowed == 1
    assert snapshot.total_denied == 1


@pytest.mark.asyncio
async def test_token_bucket_load_isolated_between_domains() -> None:
    settings = Settings(app_env="test")
    clock = _Clock()
    bucket = DomainTokenBucket(settings, now_seconds=clock.now)

    # Domain A runs 10x above its limit, while domain B stays within limit.
    allowed_a = 0
    denied_a = 0
    allowed_b = 0
    denied_b = 0

    for _ in range(600):
        for _burst in range(10):
            decision_a = await bucket.try_take(domain_id="domain-heavy", capacity_per_hour=60)
            if decision_a.allowed:
                allowed_a += 1
            else:
                denied_a += 1

        # One request per minute against a higher cap should not be impacted by domain A load.
        decision_b = await bucket.try_take(domain_id="domain-light", capacity_per_hour=120)
        if decision_b.allowed:
            allowed_b += 1
        else:
            denied_b += 1
        clock.advance(60)

    assert denied_a > 0
    assert denied_b == 0
    assert allowed_b == 600


@pytest.mark.asyncio
async def test_daily_cap_uses_warmup_redis_override_limit() -> None:
    settings = Settings(app_env="test")
    bucket = DomainTokenBucket(settings)
    await bucket.set_daily_warmup_limit(domain_id="domain-override", daily_limit=3)

    allowed = 0
    denied = 0
    for _ in range(5):
        decision = await bucket.try_take_daily(domain_id="domain-override", daily_limit=999)
        if decision.allowed:
            allowed += 1
        else:
            denied += 1

    assert allowed == 3
    assert denied == 2
