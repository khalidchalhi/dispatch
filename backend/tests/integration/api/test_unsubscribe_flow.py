from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient

from apps.api.deps import (
    get_auth_service_dep,
    get_contact_service_dep,
    get_list_service_dep,
    get_settings_dep,
    get_user_service_dep,
)
from apps.api.main import app

AuthTestContext = Any
UserFactory = Any


@pytest.fixture
async def auth_client(auth_test_context: AuthTestContext) -> AsyncIterator[AsyncClient]:
    app.dependency_overrides[get_settings_dep] = lambda: auth_test_context.settings
    app.dependency_overrides[get_auth_service_dep] = lambda: auth_test_context.auth_service
    app.dependency_overrides[get_user_service_dep] = lambda: auth_test_context.user_service
    app.dependency_overrides[get_contact_service_dep] = lambda: auth_test_context.contact_service
    app.dependency_overrides[get_list_service_dep] = lambda: auth_test_context.list_service
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client
    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_public_unsubscribe_rejects_forged_signature(
    auth_client: AsyncClient,
    auth_user_factory: UserFactory,
) -> None:
    await auth_user_factory(
        email="admin-unsub-flow@dispatch.test",
        password="correct-password-value",
        role="admin",
    )
    login_response = await auth_client.post(
        "/auth/login",
        json={"email": "admin-unsub-flow@dispatch.test", "password": "correct-password-value"},
    )
    assert login_response.status_code == 200

    create_response = await auth_client.post(
        "/contacts",
        json={"email": "token-good@dispatch.test", "source_type": "api"},
    )
    assert create_response.status_code == 201
    contact_id = create_response.json()["id"]

    token_response = await auth_client.post(f"/contacts/{contact_id}/unsubscribe-token")
    assert token_response.status_code == 200
    valid_token = token_response.json()["token"]
    assert token_response.json()["unsubscribe_url"].endswith(
        f"/unsubscribe?t={valid_token}"
    )

    valid_unsubscribe = await auth_client.post(
        "/contacts/unsubscribe/public",
        json={"token": valid_token},
    )
    assert valid_unsubscribe.status_code == 200
    assert valid_unsubscribe.json()["message"] == "Contact unsubscribed"

    create_second = await auth_client.post(
        "/contacts",
        json={"email": "token-bad@dispatch.test", "source_type": "api"},
    )
    assert create_second.status_code == 201
    second_contact_id = create_second.json()["id"]
    second_token_response = await auth_client.post(
        f"/contacts/{second_contact_id}/unsubscribe-token"
    )
    assert second_token_response.status_code == 200
    forged_token = f"{second_token_response.json()['token']}tampered"

    forged_unsubscribe = await auth_client.post(
        "/contacts/unsubscribe/public",
        json={"token": forged_token},
    )
    assert forged_unsubscribe.status_code == 401
    forged_payload = forged_unsubscribe.json()
    assert forged_payload["error"]["code"] == "authentication_error"
