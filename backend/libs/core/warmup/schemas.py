from __future__ import annotations

from dataclasses import dataclass, field

# 30-day warmup template aligned with Sprint 15 requirements:
# day 1-3: 50/day
# day 4-7: 100/day
# day 8-14: 500/day
# day 15-21: 1K/day
# day 22-30: 5K/day
_DEFAULT_SCHEDULE: list[int] = (
    [50] * 3
    + [100] * 4
    + [500] * 7
    + [1_000] * 7
    + [5_000] * 9
)

# Tighter thresholds during warmup (half the normal circuit-breaker levels).
WARMUP_BOUNCE_RATE_THRESHOLD: float = 0.005   # 0.5%
WARMUP_COMPLAINT_RATE_THRESHOLD: float = 0.0002  # 0.02%

# Days of clean metrics required before graduation.
GRADUATION_CLEAN_DAYS: int = 3
# Days to extend warmup when health is bad.
WARMUP_EXTENSION_DAYS: int = 7


@dataclass(slots=True, frozen=True)
class WarmupSchedule:
    """Immutable value type holding a domain's day-by-day send targets."""

    volumes: list[int]

    def budget_for_day(self, day: int) -> int:
        """Return send budget for day N (1-indexed). Returns last volume once past schedule."""
        if day <= 0:
            return 0
        idx = min(day - 1, len(self.volumes) - 1)
        return self.volumes[idx]

    def total_days(self) -> int:
        return len(self.volumes)

    def is_past_schedule(self, day: int) -> bool:
        return day > len(self.volumes)


def default_warmup_schedule() -> WarmupSchedule:
    """Return the standard 30-day warmup schedule."""
    return WarmupSchedule(volumes=list(_DEFAULT_SCHEDULE))


def custom_warmup_schedule(volumes: list[int]) -> WarmupSchedule:
    """Build a warmup schedule from an explicit volume list."""
    if not volumes:
        raise ValueError("volumes must not be empty")
    if any(v < 0 for v in volumes):
        raise ValueError("all volume values must be non-negative")
    return WarmupSchedule(volumes=list(volumes))
