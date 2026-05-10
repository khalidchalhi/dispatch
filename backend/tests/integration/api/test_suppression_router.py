from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient

from apps.api.deps import (
    get_auth_service_dep,
    get_settings_dep,
    get_suppression_service_dep,
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
    app.dependency_overrides[get_suppression_service_dep] = (
        lambda: auth_test_context.suppression_service
    )
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client
    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_suppression_router_crud_list_and_bulk_import(
    auth_client: AsyncClient,
    auth_user_factory: UserFactory,
) -> None:
    await auth_user_factory(
        email="admin-suppression-router@dispatch.test",
        password="router-password-value",
        role="admin",
    )
    login_response = await auth_client.post(
        "/auth/login",
        json={
            "email": "admin-suppression-router@dispatch.test",
            "password": "router-password-value",
        },
    )
    assert login_response.status_code == 200

    create_response = await auth_client.post(
        "/suppression",
        json={
            "email": "router-one@dispatch.test",
            "reason_code": "manual",
            "source": "admin_panel",
            "sync_to_ses": False,
        },
    )
    assert create_response.status_code == 201
    created = create_response.json()
    assert created["email"] == "router-one@dispatch.test"
    assert created["reason_code"] == "manual"
    assert created["source"] == "admin_panel"

    get_response = await auth_client.get("/suppression/router-one@dispatch.test")
    assert get_response.status_code == 200
    assert get_response.json()["id"] == created["id"]

    reveal_response = await auth_client.get(f"/suppression/{created['id']}/reveal")
    assert reveal_response.status_code == 200
    reveal_payload = reveal_response.json()
    assert reveal_payload["id"] == created["id"]
    assert reveal_payload["email"] == "router-one@dispatch.test"

    list_response = await auth_client.get("/suppression?limit=50&offset=0&reason_code=manual")
    assert list_response.status_code == 200
    assert list_response.json()["total"] >= 1
    assert any(item["id"] == created["id"] for item in list_response.json()["items"])

    export_response = await auth_client.post("/suppression/export")
    assert export_response.status_code == 200
    assert export_response.headers["content-type"].startswith("text/csv")
    assert "router-one@dispatch.test" in export_response.text

    bulk_response = await auth_client.post(
        "/suppression/bulk-import",
        data={
            "reason_code": "role_account",
            "source": "csv_upload",
            "sync_to_ses": "false",
        },
        files={
            "file": (
                "suppression.csv",
                b"email\nbulk-api-one@dispatch.test\nbad-email\nbulk-api-one@dispatch.test\n",
                "text/csv",
            )
        },
    )
    assert bulk_response.status_code == 200
    bulk_payload = bulk_response.json()
    assert bulk_payload["imported_count"] == 1
    assert bulk_payload["invalid_count"] == 1
    assert bulk_payload["skipped_count"] == 1

    delete_response = await auth_client.request(
        "DELETE",
        "/suppression/router-one@dispatch.test",
        json={"justification": "False positive suppression"},
    )
    assert delete_response.status_code == 204

    deleted_get = await auth_client.get("/suppression/router-one@dispatch.test")
    assert deleted_get.status_code == 404


@pytest.mark.asyncio
async def test_suppression_router_removal_rate_limit_enforced(
    auth_client: AsyncClient,
    auth_user_factory: UserFactory,
) -> None:
    await auth_user_factory(
        email="admin-suppression-limit@dispatch.test",
        password="router-password-value",
        role="admin",
    )
    login_response = await auth_client.post(
        "/auth/login",
        json={
            "email": "admin-suppression-limit@dispatch.test",
            "password": "router-password-value",
        },
    )
    assert login_response.status_code == 200

    for email in (
        "limit-one@dispatch.test",
        "limit-two@dispatch.test",
        "limit-three@dispatch.test",
    ):
        created = await auth_client.post(
            "/suppression",
            json={
                "email": email,
                "reason_code": "manual",
                "source": "admin_panel",
                "sync_to_ses": False,
            },
        )
        assert created.status_code == 201

    delete_one = await auth_client.request(
        "DELETE",
        "/suppression/limit-one@dispatch.test",
        json={"justification": "reviewed and restored"},
    )
    assert delete_one.status_code == 204

    delete_two = await auth_client.request(
        "DELETE",
        "/suppression/limit-two@dispatch.test",
        json={"justification": "reviewed and restored"},
    )
    assert delete_two.status_code == 204

    delete_three = await auth_client.request(
        "DELETE",
        "/suppression/limit-three@dispatch.test",
        json={"justification": "must be rate limited"},
    )
    assert delete_three.status_code == 429
    assert delete_three.json()["error"]["code"] == "rate_limited"
