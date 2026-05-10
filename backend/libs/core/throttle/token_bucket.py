from __future__ import annotations

import math
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from functools import lru_cache
from typing import Protocol, cast

from redis import asyncio as redis_async

from libs.core.config import Settings, get_settings
from libs.core.logging import get_logger

logger = get_logger("core.throttle")

_DAILY_CAP_LUA = """
local key = KEYS[1]
local daily_limit = tonumber(ARGV[1])
local ttl_seconds = tonumber(ARGV[2])

local count = redis.call("INCR", key)
if count == 1 then
    redis.call("EXPIRE", key, ttl_seconds)
end

if count > daily_limit then
    redis.call("DECR", key)
    return {0, count - 1}
end

return {1, daily_limit - count}
"""

_TOKEN_BUCKET_LUA = """
local key = KEYS[1]
local capacity = tonumber(ARGV[1])
local refill_rate_per_sec = tonumber(ARGV[2])
local now_ms = tonumber(ARGV[3])
local requested = tonumber(ARGV[4])
local ttl_seconds = tonumber(ARGV[5])

local state = redis.call("HMGET", key, "tokens", "ts_ms")
local tokens = tonumber(state[1])
local last_ms = tonumber(state[2])

if tokens == nil then
    tokens = capacity
end
if last_ms == nil then
    last_ms = now_ms
end

local elapsed_ms = now_ms - last_ms
if elapsed_ms < 0 then
    elapsed_ms = 0
end

tokens = math.min(capacity, tokens + (elapsed_ms / 1000.0) * refill_rate_per_sec)

local allowed = 0
local retry_after_seconds = 0

if tokens >= requested then
    tokens = tokens - requested
    allowed = 1
else
    local deficit = requested - tokens
    retry_after_seconds = math.ceil(deficit / refill_rate_per_sec)
end

redis.call("HMSET", key, "tokens", tokens, "ts_ms", now_ms)
redis.call("EXPIRE", key, ttl_seconds)

return {allowed, retry_after_seconds, math.floor(tokens)}
"""


@dataclass(frozen=True, slots=True)
class DailyCapDecision:
    allowed: bool
    tokens_remaining: int | None


@dataclass(frozen=True, slots=True)
class TokenBucketDecision:
    allowed: bool
    retry_after_seconds: int
    tokens_remaining: int | None


@dataclass(frozen=True, slots=True)
class TokenBucketMetricEvent:
    domain_id: str
    allowed: bool
    retry_after_seconds: int
    tokens_remaining: int | None
    source: str


@dataclass(frozen=True, slots=True)
class TokenBucketMetricSnapshot:
    domain_id: str
    tokens_available: int | None
    denials_last_minute: int
    denial_rate_per_minute: float
    total_allowed: int
    total_denied: int
    updated_at: datetime | None


class TokenBucketMetricsRecorder(Protocol):
    def record(
        self,
        *,
        domain_id: str,
        allowed: bool,
        retry_after_seconds: int,
        tokens_remaining: int | None,
        source: str,
    ) -> None: ...


class NoopTokenBucketMetricsRecorder:
    def record(
        self,
        *,
        domain_id: str,
        allowed: bool,
        retry_after_seconds: int,
        tokens_remaining: int | None,
        source: str,
    ) -> None:
        _ = (domain_id, allowed, retry_after_seconds, tokens_remaining, source)


@dataclass(slots=True)
class InMemoryTokenBucketMetricsRecorder:
    events: list[TokenBucketMetricEvent] = field(default_factory=list)

    def record(
        self,
        *,
        domain_id: str,
        allowed: bool,
        retry_after_seconds: int,
        tokens_remaining: int | None,
        source: str,
    ) -> None:
        self.events.append(
            TokenBucketMetricEvent(
                domain_id=domain_id,
                allowed=allowed,
                retry_after_seconds=retry_after_seconds,
                tokens_remaining=tokens_remaining,
                source=source,
            )
        )

    def snapshot(self, domain_id: str) -> TokenBucketMetricSnapshot:
        cleaned = domain_id.strip()
        relevant = [event for event in self.events if event.domain_id == cleaned]
        if not relevant:
            return TokenBucketMetricSnapshot(
                domain_id=cleaned,
                tokens_available=None,
                denials_last_minute=0,
                denial_rate_per_minute=0.0,
                total_allowed=0,
                total_denied=0,
                updated_at=None,
            )

        total_allowed = sum(1 for event in relevant if event.allowed)
        total_denied = len(relevant) - total_allowed
        return TokenBucketMetricSnapshot(
            domain_id=cleaned,
            tokens_available=relevant[-1].tokens_remaining,
            denials_last_minute=total_denied,
            denial_rate_per_minute=float(total_denied),
            total_allowed=total_allowed,
            total_denied=total_denied,
            updated_at=datetime.now(UTC),
        )


@dataclass(slots=True)
class TokenBucketMetricsStore(TokenBucketMetricsRecorder):
    _events_by_domain: dict[str, list[tuple[float, bool]]] = field(default_factory=dict)
    _last_tokens: dict[str, int | None] = field(default_factory=dict)
    _totals_allowed: dict[str, int] = field(default_factory=dict)
    _totals_denied: dict[str, int] = field(default_factory=dict)
    _updated_at: dict[str, datetime] = field(default_factory=dict)
    _window_seconds: int = 60

    def __init__(self, *, window_seconds: int = 60) -> None:
        self._events_by_domain = {}
        self._last_tokens = {}
        self._totals_allowed = {}
        self._totals_denied = {}
        self._updated_at = {}
        self._window_seconds = max(window_seconds, 1)

    def record(
        self,
        *,
        domain_id: str,
        allowed: bool,
        retry_after_seconds: int,
        tokens_remaining: int | None,
        source: str,
    ) -> None:
        _ = (retry_after_seconds, source)
        now_ts = time.time()
        cleaned = domain_id.strip()
        if not cleaned:
            return
        events = self._events_by_domain.setdefault(cleaned, [])
        events.append((now_ts, allowed))
        cutoff = now_ts - self._window_seconds
        self._events_by_domain[cleaned] = [
            event for event in events if event[0] >= cutoff
        ]
        self._last_tokens[cleaned] = tokens_remaining
        if allowed:
            self._totals_allowed[cleaned] = self._totals_allowed.get(cleaned, 0) + 1
        else:
            self._totals_denied[cleaned] = self._totals_denied.get(cleaned, 0) + 1
        self._updated_at[cleaned] = datetime.now(UTC)

    def snapshot(self, domain_id: str) -> TokenBucketMetricSnapshot:
        cleaned = domain_id.strip()
        events = self._events_by_domain.get(cleaned, [])
        cutoff = time.time() - self._window_seconds
        events = [event for event in events if event[0] >= cutoff]
        self._events_by_domain[cleaned] = events
        denials = sum(1 for _, allowed in events if not allowed)
        return TokenBucketMetricSnapshot(
            domain_id=cleaned,
            tokens_available=self._last_tokens.get(cleaned),
            denials_last_minute=denials,
            denial_rate_per_minute=float(denials),
            total_allowed=self._totals_allowed.get(cleaned, 0),
            total_denied=self._totals_denied.get(cleaned, 0),
            updated_at=self._updated_at.get(cleaned),
        )


@dataclass(slots=True)
class _FallbackBucketState:
    tokens: float
    timestamp_seconds: float


class _RedisTokenBucketClient(Protocol):
    async def script_load(self, script: str) -> str: ...

    async def evalsha(self, sha: str, numkeys: int, *keys_and_args: object) -> object: ...

    async def get(self, name: str) -> object: ...

    async def set(self, name: str, value: object, ex: int | None = None) -> object: ...


class DomainTokenBucket:
    def __init__(
        self,
        settings: Settings,
        *,
        redis_client: _RedisTokenBucketClient | None = None,
        metrics: TokenBucketMetricsRecorder | None = None,
        now_seconds: Callable[[], float] | None = None,
    ) -> None:
        self._settings = settings
        self._redis_client = redis_client or cast(
            _RedisTokenBucketClient,
            redis_async.from_url(settings.redis_url, decode_responses=True),  # type: ignore[no-untyped-call]
        )
        self._metrics = metrics or get_token_bucket_metrics_store()
        self._now_seconds = now_seconds or time.time
        self._script_sha: str | None = None
        self._daily_cap_sha: str | None = None
        self._fallback_buckets: dict[str, _FallbackBucketState] = {}
        self._fallback_daily_counters: dict[str, int] = {}
        self._fallback_warmup_daily_limits: dict[str, int] = {}

    async def try_take(
        self,
        *,
        domain_id: str,
        capacity_per_hour: int,
        requested_tokens: int = 1,
    ) -> TokenBucketDecision:
        normalized_domain_id = domain_id.strip()
        if not normalized_domain_id:
            return self._record_and_return(
                domain_id="unknown",
                decision=TokenBucketDecision(
                    allowed=False,
                    retry_after_seconds=max(self._settings.throttle_fail_closed_retry_seconds, 1),
                    tokens_remaining=None,
                ),
                source="invalid_domain",
            )

        capacity = max(capacity_per_hour, 1)
        requested = max(requested_tokens, 1)
        refill_rate_per_sec = capacity / 3600.0

        if self._settings.app_env == "test":
            decision = self._try_take_fallback(
                domain_id=normalized_domain_id,
                capacity=capacity,
                requested=requested,
                refill_rate_per_sec=refill_rate_per_sec,
            )
            return self._record_and_return(
                domain_id=normalized_domain_id,
                decision=decision,
                source="fallback",
            )

        try:
            decision = await self._try_take_redis(
                domain_id=normalized_domain_id,
                capacity=capacity,
                requested=requested,
                refill_rate_per_sec=refill_rate_per_sec,
            )
            return self._record_and_return(
                domain_id=normalized_domain_id,
                decision=decision,
                source="redis",
            )
        except Exception as exc:
            logger.warning(
                "throttle.redis_unavailable_fail_closed",
                domain_id=normalized_domain_id,
                error=str(exc),
            )
            decision = TokenBucketDecision(
                allowed=False,
                retry_after_seconds=max(self._settings.throttle_fail_closed_retry_seconds, 1),
                tokens_remaining=None,
            )
            return self._record_and_return(
                domain_id=normalized_domain_id,
                decision=decision,
                source="redis_error",
            )

    async def try_take_daily(
        self,
        *,
        domain_id: str,
        daily_limit: int,
    ) -> DailyCapDecision:
        """Atomically check and increment a domain's daily send counter.

        Returns allowed=False once the counter reaches daily_limit. The counter
        expires automatically at the configured TTL (one day) so it resets each day.
        Only called for domains in warmup_stage='warming'.
        """
        normalized = domain_id.strip().lower()
        if not normalized:
            return DailyCapDecision(allowed=False, tokens_remaining=None)
        effective_limit = await self.resolve_daily_limit(
            domain_id=normalized,
            fallback_limit=daily_limit,
        )
        if effective_limit <= 0:
            return DailyCapDecision(allowed=True, tokens_remaining=None)

        if self._settings.app_env == "test":
            return self._try_take_daily_fallback(domain_id=normalized, daily_limit=effective_limit)

        try:
            return await self._try_take_daily_redis(
                domain_id=normalized, daily_limit=effective_limit
            )
        except Exception as exc:
            logger.warning(
                "throttle.daily_cap_redis_error",
                domain_id=normalized,
                error=str(exc),
            )
            return DailyCapDecision(allowed=False, tokens_remaining=None)

    async def set_daily_warmup_limit(
        self,
        *,
        domain_id: str,
        daily_limit: int,
    ) -> None:
        normalized = domain_id.strip().lower()
        if not normalized:
            return
        limit = max(int(daily_limit), 0)
        key = self._warmup_daily_limit_key(normalized)
        if self._settings.app_env == "test":
            self._fallback_warmup_daily_limits[key] = limit
            return

        ttl_seconds = max(self._seconds_until_next_midnight_utc() + 3600, 3600)
        await self._redis_client.set(key, str(limit), ex=ttl_seconds)

    async def resolve_daily_limit(
        self,
        *,
        domain_id: str,
        fallback_limit: int,
    ) -> int:
        normalized = domain_id.strip().lower()
        if not normalized:
            return max(int(fallback_limit), 0)
        key = self._warmup_daily_limit_key(normalized)

        if self._settings.app_env == "test":
            override = self._fallback_warmup_daily_limits.get(key)
            return max(int(override), 0) if override is not None else max(int(fallback_limit), 0)

        try:
            raw = await self._redis_client.get(key)
        except Exception as exc:
            logger.warning(
                "throttle.warmup_limit_resolve_failed",
                domain_id=normalized,
                error=str(exc),
            )
            return max(int(fallback_limit), 0)

        if raw is None:
            return max(int(fallback_limit), 0)
        try:
            return max(int(raw), 0)
        except (TypeError, ValueError):
            return max(int(fallback_limit), 0)

    def _try_take_daily_fallback(
        self, *, domain_id: str, daily_limit: int
    ) -> DailyCapDecision:
        key = f"daily:{domain_id}"
        current = self._fallback_daily_counters.get(key, 0)
        if current >= daily_limit:
            return DailyCapDecision(allowed=False, tokens_remaining=0)
        self._fallback_daily_counters[key] = current + 1
        return DailyCapDecision(allowed=True, tokens_remaining=daily_limit - (current + 1))

    async def _try_take_daily_redis(
        self, *, domain_id: str, daily_limit: int
    ) -> DailyCapDecision:
        if self._daily_cap_sha is None:
            self._daily_cap_sha = await self._redis_client.script_load(_DAILY_CAP_LUA)

        from datetime import UTC, datetime

        today = datetime.now(UTC).strftime("%Y-%m-%d")
        key = f"throttle:daily:{domain_id}:{today}"
        ttl = self._settings.throttle_bucket_ttl_seconds
        raw = await self._redis_client.evalsha(
            self._daily_cap_sha, 1, key, str(daily_limit), str(ttl)
        )
        if not isinstance(raw, list) or len(raw) != 2:
            raise RuntimeError("Unexpected daily cap Lua response")
        allowed = int(raw[0]) == 1
        remaining = int(raw[1])
        return DailyCapDecision(allowed=allowed, tokens_remaining=max(remaining, 0))

    def reset_daily_counters(self) -> None:
        """Test helper to clear all in-memory daily counters."""
        self._fallback_daily_counters.clear()
        self._fallback_warmup_daily_limits.clear()

    @staticmethod
    def queue_key_for_domain(domain_id: str) -> str:
        return f"throttle:domain:{domain_id.strip().lower()}"

    @staticmethod
    def _warmup_daily_limit_key(domain_id: str) -> str:
        today = datetime.now(UTC).strftime("%Y-%m-%d")
        return f"throttle:warmup:daily_limit:{domain_id.strip().lower()}:{today}"

    @staticmethod
    def _seconds_until_next_midnight_utc() -> int:
        now = datetime.now(UTC)
        next_midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
        next_midnight = next_midnight + timedelta(days=1)
        return max(int((next_midnight - now).total_seconds()), 1)

    async def _try_take_redis(
        self,
        *,
        domain_id: str,
        capacity: int,
        requested: int,
        refill_rate_per_sec: float,
    ) -> TokenBucketDecision:
        if self._script_sha is None:
            self._script_sha = await self._redis_client.script_load(_TOKEN_BUCKET_LUA)

        now_ms = int(self._now_seconds() * 1000)
        key = self.queue_key_for_domain(domain_id)
        args: tuple[object, ...] = (
            key,
            str(capacity),
            f"{refill_rate_per_sec:.10f}",
            str(now_ms),
            str(requested),
            str(self._settings.throttle_bucket_ttl_seconds),
        )
        raw = await self._redis_client.evalsha(self._script_sha, 1, *args)
        return self._parse_script_result(raw)

    def _try_take_fallback(
        self,
        *,
        domain_id: str,
        capacity: int,
        requested: int,
        refill_rate_per_sec: float,
    ) -> TokenBucketDecision:
        now = self._now_seconds()
        key = self.queue_key_for_domain(domain_id)
        state = self._fallback_buckets.get(key)
        if state is None:
            state = _FallbackBucketState(tokens=float(capacity), timestamp_seconds=now)
            self._fallback_buckets[key] = state

        elapsed = max(0.0, now - state.timestamp_seconds)
        state.tokens = min(float(capacity), state.tokens + elapsed * refill_rate_per_sec)
        state.timestamp_seconds = now

        if state.tokens >= requested:
            state.tokens -= requested
            return TokenBucketDecision(
                allowed=True,
                retry_after_seconds=0,
                tokens_remaining=max(int(state.tokens), 0),
            )

        deficit = requested - state.tokens
        retry_after_seconds = int(math.ceil(deficit / refill_rate_per_sec))
        return TokenBucketDecision(
            allowed=False,
            retry_after_seconds=max(retry_after_seconds, 1),
            tokens_remaining=max(int(state.tokens), 0),
        )

    @staticmethod
    def _parse_script_result(raw: object) -> TokenBucketDecision:
        if not isinstance(raw, list) or len(raw) != 3:
            raise RuntimeError("Unexpected token bucket Lua response format")

        allowed_raw = int(raw[0])
        retry_raw = int(raw[1])
        remaining_raw = int(raw[2])
        return TokenBucketDecision(
            allowed=allowed_raw == 1,
            retry_after_seconds=max(retry_raw, 0),
            tokens_remaining=max(remaining_raw, 0),
        )

    def _record_and_return(
        self,
        *,
        domain_id: str,
        decision: TokenBucketDecision,
        source: str,
    ) -> TokenBucketDecision:
        self._metrics.record(
            domain_id=domain_id,
            allowed=decision.allowed,
            retry_after_seconds=decision.retry_after_seconds,
            tokens_remaining=decision.tokens_remaining,
            source=source,
        )
        return decision


@lru_cache(maxsize=1)
def get_domain_token_bucket() -> DomainTokenBucket:
    return DomainTokenBucket(get_settings())


def reset_domain_token_bucket_cache() -> None:
    get_domain_token_bucket.cache_clear()


@lru_cache(maxsize=1)
def get_token_bucket_metrics_store() -> TokenBucketMetricsStore:
    return TokenBucketMetricsStore()


def reset_token_bucket_metrics_store() -> None:
    get_token_bucket_metrics_store.cache_clear()
