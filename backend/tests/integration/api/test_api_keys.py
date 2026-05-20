from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient

from apps.api.deps import get_auth_service_dep, get_settings_dep, get_user_service_dep
from apps.api.main import app

AuthTestContext = Any
UserFactory = Any


@pytest.fixture
async def auth_client(auth_test_context: AuthTestContext) -> AsyncIterator[AsyncClient]:
    app.dependency_overrides[get_settings_dep] = lambda: auth_test_context.settings
    app.dependency_overrides[get_auth_service_dep] = lambda: auth_test_context.auth_service
    app.dependency_overrides[get_user_service_dep] = lambda: auth_test_context.user_service
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client
    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_api_key_lifecycle_for_user(
    auth_client: AsyncClient,
    auth_user_factory: UserFactory,
) -> None:
    await auth_user_factory(
        email="keys-route@example.com",
        password="correct-password-value",
    )

    login_response = await auth_client.post(
        "/auth/login",
        json={"email": "keys-route@example.com", "password": "correct-password-value"},
    )
    assert login_response.status_code == 200

    create_response = await auth_client.post(
        "/users/me/api-keys",
        json={"name": "automation"},
    )
    assert create_response.status_code == 201
    plaintext_key = create_response.json()["plaintext_key"]
    key_id = create_response.json()["api_key"]["id"]
    assert plaintext_key.startswith("ak_live_")

    with_api_key = await auth_client.get(
        "/users/me",
        headers={"Authorization": f"Bearer {plaintext_key}"},
    )
    assert with_api_key.status_code == 200
    assert with_api_key.json()["email"] == "keys-route@example.com"

    list_response = await auth_client.get("/users/me/api-keys")
    assert list_response.status_code == 200
    assert len(list_response.json()) == 1

    auth_alias_response = await auth_client.get("/auth/api-keys")
    assert auth_alias_response.status_code == 200
    assert auth_alias_response.json()[0]["id"] == key_id

    rotate_response = await auth_client.post(
        f"/users/me/api-keys/{key_id}/rotate",
        json={"name": "automation-rotated"},
    )
    assert rotate_response.status_code == 200
    rotated_plaintext = rotate_response.json()["plaintext_key"]
    rotated_id = rotate_response.json()["api_key"]["id"]
    assert rotated_plaintext != plaintext_key

    old_key_rejected = await auth_client.get(
        "/users/me",
        headers={"Authorization": f"Bearer {plaintext_key}"},
    )
    assert old_key_rejected.status_code == 401

    revoke_response = await auth_client.delete(f"/users/me/api-keys/{rotated_id}")
    assert revoke_response.status_code == 200

    revoked_key_rejected = await auth_client.get(
        "/users/me",
        headers={"Authorization": f"Bearer {rotated_plaintext}"},
    )
    assert revoked_key_rejected.status_code == 401


@pytest.mark.asyncio
async def test_admin_guards_user_management_endpoints(
    auth_client: AsyncClient,
    auth_user_factory: UserFactory,
) -> None:
    admin = await auth_user_factory(
        email="admin@example.com",
        password="admin-password-value",
        role="admin",
    )
    await auth_user_factory(
        email="member@example.com",
        password="member-password-value",
        role="user",
    )
    mfa_member = await auth_user_factory(
        email="mfa-member@example.com",
        password="mfa-member-password-value",
        role="user",
        mfa_enabled=True,
    )

    await auth_client.post(
        "/auth/login",
        json={"email": "member@example.com", "password": "member-password-value"},
    )
    forbidden_create = await auth_client.post(
        "/users",
        json={"email": "new@example.com", "password": "new-password-value", "role": "user"},
    )
    assert forbidden_create.status_code == 403

    forbidden_get = await auth_client.get(f"/users/{admin.id}")
    assert forbidden_get.status_code == 403

    forbidden_mfa_reset = await auth_client.post(f"/users/{admin.id}/reset-mfa")
    assert forbidden_mfa_reset.status_code == 403

    # Login as admin in a fresh client to avoid cookie overlap.
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as admin_client:
        await admin_client.post(
            "/auth/login",
            json={"email": "admin@example.com", "password": "admin-password-value"},
        )
        create_response = await admin_client.post(
            "/users",
            json={"email": "new@example.com", "password": "new-password-value", "role": "user"},
        )
        assert create_response.status_code == 201
        user_id = create_response.json()["id"]

        get_response = await admin_client.get(f"/users/{user_id}")
        assert get_response.status_code == 200
        assert get_response.json()["email"] == "new@example.com"

        list_response = await admin_client.get("/users")
        assert list_response.status_code == 200
        assert any(item["email"] == "new@example.com" for item in list_response.json()["items"])

        reset_mfa_response = await admin_client.post(f"/users/{mfa_member.id}/reset-mfa")
        assert reset_mfa_response.status_code == 200

        member_response = await admin_client.get(f"/users/{mfa_member.id}")
        assert member_response.status_code == 200
        assert member_response.json()["mfa_enabled"] is False

        disable_response = await admin_client.post(
            f"/users/{user_id}/disable",
            json={"reason": "disabled in test"},
        )
        assert disable_response.status_code == 200
