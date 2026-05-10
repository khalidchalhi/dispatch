from __future__ import annotations

from uuid import uuid4

import pytest
from redis import asyncio as redis_async

from libs.core.config import Settings
from libs.core.throttle.token_bucket import DomainTokenBucket


@pytest.mark.asyncio
async def test_token_bucket_redis_denies_after_capacity_exhausted() -> None:
    settings = Settings(app_env="local", redis_url="redis://localhost:6379/0")
    redis = redis_async.from_url(settings.redis_url, decode_responses=True)  # type: ignore[no-untyped-call]

    try:
        try:
            await redis.ping()
        except Exception:
            pytest.skip("Redis is not available on localhost:6379")

        bucket = DomainTokenBucket(settings, redis_client=redis)
        domain_id = f"redis-throttle-{uuid4().hex}"
        key = bucket.queue_key_for_domain(domain_id)

        await redis.delete(key)
        first = await bucket.try_take(domain_id=domain_id, capacity_per_hour=1)
        second = await bucket.try_take(domain_id=domain_id, capacity_per_hour=1)

        assert first.allowed is True
        assert second.allowed is False
        assert second.retry_after_seconds > 0
    finally:
        await redis.aclose()


@pytest.mark.asyncio
async def test_token_bucket_redis_load_isolation_between_domains() -> None:
    settings = Settings(app_env="local", redis_url="redis://localhost:6379/0")
    redis = redis_async.from_url(settings.redis_url, decode_responses=True)  # type: ignore[no-untyped-call]

    try:
        try:
            await redis.ping()
        except Exception:
            pytest.skip("Redis is not available on localhost:6379")

        bucket = DomainTokenBucket(settings, redis_client=redis)
        domain_heavy = f"redis-heavy-{uuid4().hex}"
        domain_light = f"redis-light-{uuid4().hex}"
        key_heavy = bucket.queue_key_for_domain(domain_heavy)
        key_light = bucket.queue_key_for_domain(domain_light)

        await redis.delete(key_heavy, key_light)

        # Heavy domain: 10 requests against a 1/hour capacity (10x pressure).
        heavy_results = [
            await bucket.try_take(domain_id=domain_heavy, capacity_per_hour=1)
            for _ in range(10)
        ]
        # Light domain: one request at its own 10/hour capacity (1x pressure).
        light_result = await bucket.try_take(domain_id=domain_light, capacity_per_hour=10)

        heavy_denied = sum(1 for decision in heavy_results if not decision.allowed)
        assert heavy_denied > 0
        assert light_result.allowed is True
    finally:
        await redis.aclose()
