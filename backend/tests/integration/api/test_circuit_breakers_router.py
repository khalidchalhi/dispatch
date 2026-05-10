from __future__ import annotations

from collections.abc import AsyncIterator
from decimal import Decimal
from typing import Any
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from apps.api.deps import (
    get_auth_service_dep,
    get_circuit_breaker_service_dep,
    get_settings_dep,
    get_user_service_dep,
)
from apps.api.main import app
from libs.core.circuit_breaker.service import CircuitBreakerService
from libs.core.db.uow import UnitOfWork
from libs.core.domains.models import Domain

AuthTestContext = Any
UserFactory = Any


@pytest.fixture
async def auth_client(auth_test_context: AuthTestContext) -> AsyncIterator[AsyncClient]:
    circuit_breaker_service = CircuitBreakerService(auth_test_context.settings)
    app.dependency_overrides[get_settings_dep] = lambda: auth_test_context.settings
    app.dependency_overrides[get_auth_service_dep] = lambda: auth_test_context.auth_service
    app.dependency_overrides[get_user_service_dep] = lambda: auth_test_context.user_service
    app.dependency_overrides[get_circuit_breaker_service_dep] = lambda: circuit_breaker_service
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client
    app.dependency_overrides.clear()


async def _seed_verified_domain(auth_test_context: AuthTestContext) -> str:
    unique = uuid4().hex[:8]
    async with UnitOfWork(auth_test_context.session_factory) as uow:
        domain = Domain(
            name=f"cb-router-{unique}.dispatch.test",
            verification_status="verified",
            spf_status="verified",
            dkim_status="verified",
            dmarc_status="verified",
            reputation_status="healthy",
        )
        uow.require_session().add(domain)
        await uow.require_session().flush()
        return domain.id


@pytest.mark.asyncio
async def test_circuit_breakers_router_list_status_and_reset(
    auth_test_context: AuthTestContext,
    auth_user_factory: UserFactory,
    auth_client: AsyncClient,
) -> None:
    admin = await auth_user_factory(
        email="admin-cb-router@dispatch.test",
        password="correct-password-value",
        role="admin",
    )
    login_response = await auth_client.post(
        "/auth/login",
        json={
            "email": "admin-cb-router@dispatch.test",
            "password": "correct-password-value",
        },
    )
    assert login_response.status_code == 200

    domain_id = await _seed_verified_domain(auth_test_context)
    service = CircuitBreakerService(auth_test_context.settings)
    await service.trip(
        scope_type="domain",
        scope_id=domain_id,
        reason_code="bounce_threshold",
        bounce_rate_24h=Decimal("0.0200"),
        complaint_rate_24h=Decimal("0.0000"),
    )

    list_response = await auth_client.get("/circuit-breakers")
    assert list_response.status_code == 200
    list_payload = list_response.json()
    assert "items" in list_payload
    domain_item = next(
        item
        for item in list_payload["items"]
        if item["scope_type"] == "domain" and item["scope_id"] == domain_id
    )
    assert domain_item["state"] == "open"
    breaker_id = domain_item["id"]

    scope_response = await auth_client.get(f"/circuit-breakers/scope/domain/{domain_id}")
    assert scope_response.status_code == 200
    assert scope_response.json()["id"] == breaker_id

    by_id_response = await auth_client.get(f"/circuit-breakers/{breaker_id}")
    assert by_id_response.status_code == 200
    assert by_id_response.json()["scope_type"] == "domain"

    short_reset = await auth_client.post(
        f"/circuit-breakers/{breaker_id}/reset",
        json={"justification": "too short"},
    )
    assert short_reset.status_code == 422

    reset_response = await auth_client.post(
        f"/circuit-breakers/{breaker_id}/reset",
        json={"justification": "Metrics are clean and validated after investigation."},
    )
    assert reset_response.status_code == 200
    assert reset_response.json()["message"] == "Circuit breaker reset"

    refreshed = await auth_client.get(f"/circuit-breakers/{breaker_id}")
    assert refreshed.status_code == 200
    refreshed_payload = refreshed.json()
    assert refreshed_payload["state"] == "closed"
    assert refreshed_payload["reset_by"] == admin.id
    assert refreshed_payload["reset_at"] is not None
