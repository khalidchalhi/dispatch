from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import uuid4

import pytest
from sqlalchemy import select

from libs.core.auth.models import AuditLog
from libs.core.circuit_breaker.models import AnomalyAlert, CircuitBreakerState
from libs.core.circuit_breaker.service import CircuitBreakerService
from libs.core.db.uow import UnitOfWork
from libs.core.domains.models import Domain
from libs.core.events.models import RollingMetric

AuthTestContext = Any
UserFactory = Any


class _FailingRedisClient:
    async def get(self, key: str) -> object:
        _ = key
        raise RuntimeError("redis unavailable")

    async def setex(self, key: str, ttl: int, value: str) -> object:
        _ = (key, ttl, value)
        raise RuntimeError("redis unavailable")

    async def delete(self, key: str) -> object:
        _ = key
        raise RuntimeError("redis unavailable")


class _RecordingRedisClient:
    def __init__(self) -> None:
        self.store: dict[str, str] = {}
        self.setex_calls: list[tuple[str, int, str]] = []

    async def get(self, key: str) -> object:
        return self.store.get(key)

    async def setex(self, key: str, ttl: int, value: str) -> object:
        self.store[key] = value
        self.setex_calls.append((key, ttl, value))
        return "OK"

    async def delete(self, key: str) -> object:
        self.store.pop(key, None)
        return 1


async def _create_verified_domain(auth_test_context: AuthTestContext) -> str:
    unique = uuid4().hex[:8]
    async with UnitOfWork(auth_test_context.session_factory) as uow:
        domain = Domain(
            name=f"cb-{unique}.dispatch.test",
            verification_status="verified",
            spf_status="verified",
            dkim_status="verified",
            dmarc_status="verified",
            reputation_status="healthy",
        )
        uow.require_session().add(domain)
        await uow.require_session().flush()
        return domain.id


async def _upsert_rolling_metric(
    auth_test_context: AuthTestContext,
    *,
    scope_type: str,
    scope_id: str,
    sends: int,
    bounces: int,
    complaints: int,
    bounce_rate: Decimal | None,
    complaint_rate: Decimal | None,
) -> None:
    async with UnitOfWork(auth_test_context.session_factory) as uow:
        metric = RollingMetric(
            scope_type=scope_type,
            scope_id=scope_id,
            window="24h",
            window_end=datetime.now(UTC),
            sends=sends,
            deliveries=max(sends - bounces - complaints, 0),
            bounces=bounces,
            complaints=complaints,
            opens=0,
            clicks=0,
            replies=0,
            unsubscribes=0,
            bounce_rate=bounce_rate,
            complaint_rate=complaint_rate,
            updated_at=datetime.now(UTC),
        )
        uow.require_session().add(metric)
        await uow.require_session().flush()


@pytest.mark.asyncio
async def test_is_open_defaults_to_closed_when_state_missing(
    auth_test_context: AuthTestContext,
) -> None:
    service = CircuitBreakerService(auth_test_context.settings)
    assert await service.is_open(scope_type="domain", scope_id=str(uuid4())) is False


@pytest.mark.asyncio
async def test_is_open_fail_closed_when_redis_errors(
    auth_test_context: AuthTestContext,
) -> None:
    settings = auth_test_context.settings.model_copy(update={"app_env": "local"})
    service = CircuitBreakerService(settings, redis_client=_FailingRedisClient())
    assert await service.is_open(scope_type="domain", scope_id=str(uuid4())) is True


@pytest.mark.asyncio
async def test_is_open_uses_10_second_cache_ttl(
    auth_test_context: AuthTestContext,
) -> None:
    scope_id = await _create_verified_domain(auth_test_context)
    redis_client = _RecordingRedisClient()
    settings = auth_test_context.settings.model_copy(update={"app_env": "local"})
    service = CircuitBreakerService(settings, redis_client=redis_client)

    await service.trip(
        scope_type="domain",
        scope_id=scope_id,
        reason_code="bounce_threshold",
        bounce_rate_24h=Decimal("0.0200"),
        complaint_rate_24h=Decimal("0.0000"),
    )
    is_open = await service.is_open(scope_type="domain", scope_id=scope_id)

    assert is_open is True
    assert len(redis_client.setex_calls) >= 1
    assert redis_client.setex_calls[-1][1] == 10


@pytest.mark.asyncio
async def test_trip_and_reset_write_audit_and_alert(
    auth_test_context: AuthTestContext,
    auth_user_factory: UserFactory,
) -> None:
    service = CircuitBreakerService(auth_test_context.settings)
    scope_id = str(uuid4())
    admin = await auth_user_factory(
        email=f"cb-admin-{uuid4().hex[:8]}@dispatch.test",
        password="cb-reset-password",
        role="admin",
    )

    tripped = await service.trip(
        scope_type="domain",
        scope_id=scope_id,
        reason_code="bounce_threshold",
        bounce_rate_24h=Decimal("0.0200"),
        complaint_rate_24h=Decimal("0.0001"),
    )
    assert tripped.state == "open"

    reset = await service.reset(
        scope_type="domain",
        scope_id=scope_id,
        actor_user_id=admin.id,
        reason="investigation complete",
    )
    assert reset.state == "closed"
    assert reset.reset_by == admin.id

    async with UnitOfWork(auth_test_context.session_factory) as uow:
        alerts = (
            await uow.require_session().execute(
                select(AnomalyAlert).where(AnomalyAlert.scope_id == scope_id)
            )
        ).scalars().all()
        audits = (
            await uow.require_session().execute(
                select(AuditLog)
                .where(AuditLog.action.in_(["circuit_breaker.trip", "circuit_breaker.reset"]))
                .order_by(AuditLog.id.asc())
            )
        ).scalars().all()

    assert len(alerts) == 1
    assert [entry.action for entry in audits] == ["circuit_breaker.trip", "circuit_breaker.reset"]


@pytest.mark.asyncio
async def test_evaluator_trips_domain_scope_on_threshold_breach(
    auth_test_context: AuthTestContext,
) -> None:
    service = CircuitBreakerService(auth_test_context.settings)
    domain_id = await _create_verified_domain(auth_test_context)
    await _upsert_rolling_metric(
        auth_test_context,
        scope_type="domain",
        scope_id=domain_id,
        sends=100,
        bounces=2,
        complaints=0,
        bounce_rate=Decimal("0.0200"),
        complaint_rate=Decimal("0.0000"),
    )

    result = await service.evaluate_circuit_breakers()
    assert result.tripped >= 1

    async with UnitOfWork(auth_test_context.session_factory) as uow:
        state = await uow.require_session().get(CircuitBreakerState, domain_id)
        if state is None:
            state = (
                await uow.require_session().execute(
                    select(CircuitBreakerState)
                    .where(CircuitBreakerState.scope_type == "domain")
                    .where(CircuitBreakerState.scope_id == domain_id)
                )
            ).scalar_one_or_none()
    assert state is not None
    assert state.state == "open"


@pytest.mark.asyncio
async def test_evaluator_auto_half_open_then_closes(
    auth_test_context: AuthTestContext,
) -> None:
    service = CircuitBreakerService(auth_test_context.settings)
    domain_id = await _create_verified_domain(auth_test_context)
    await _upsert_rolling_metric(
        auth_test_context,
        scope_type="domain",
        scope_id=domain_id,
        sends=200,
        bounces=0,
        complaints=0,
        bounce_rate=Decimal("0.0000"),
        complaint_rate=Decimal("0.0000"),
    )

    async with UnitOfWork(auth_test_context.session_factory) as uow:
        uow.require_session().add(
            CircuitBreakerState(
                scope_type="domain",
                scope_id=domain_id,
                state="open",
                bounce_rate_24h=Decimal("0.0200"),
                complaint_rate_24h=Decimal("0.0000"),
                tripped_reason="manual_seed",
                tripped_at=datetime.now(UTC) - timedelta(hours=25),
                auto_reset_at=datetime.now(UTC) - timedelta(minutes=5),
            )
        )
        await uow.require_session().flush()

    first = await service.evaluate_circuit_breakers()
    assert first.moved_to_half_open >= 1

    second = await service.evaluate_circuit_breakers()
    assert second.closed >= 1

    async with UnitOfWork(auth_test_context.session_factory) as uow:
        state = (
            await uow.require_session().execute(
                select(CircuitBreakerState)
                .where(CircuitBreakerState.scope_type == "domain")
                .where(CircuitBreakerState.scope_id == domain_id)
            )
        ).scalar_one_or_none()
    assert state is not None
    assert state.state == "closed"
