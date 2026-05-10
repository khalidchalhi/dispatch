from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient

from apps.api.deps import (
    get_auth_service_dep,
    get_segment_service_dep,
    get_settings_dep,
    get_user_service_dep,
)
from apps.api.main import app
from libs.core.auth.schemas import CurrentActor
from libs.core.contacts.schemas import ContactCreateRequest

AuthTestContext = Any
UserFactory = Any


@pytest.fixture
async def auth_client(auth_test_context: AuthTestContext) -> AsyncIterator[AsyncClient]:
    app.dependency_overrides[get_settings_dep] = lambda: auth_test_context.settings
    app.dependency_overrides[get_auth_service_dep] = lambda: auth_test_context.auth_service
    app.dependency_overrides[get_user_service_dep] = lambda: auth_test_context.user_service
    app.dependency_overrides[get_segment_service_dep] = lambda: auth_test_context.segment_service
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client
    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_segments_router_crud_and_preview(
    auth_client: AsyncClient,
    auth_test_context: AuthTestContext,
    auth_user_factory: UserFactory,
) -> None:
    admin_user = await auth_user_factory(
        email="admin-segments-router@dispatch.test",
        password="correct-password-value",
        role="admin",
    )
    actor = CurrentActor(actor_type="user", user=admin_user)
    active = await auth_test_context.contact_service.create_contact(
        actor=actor,
        payload=ContactCreateRequest(
            email="segment-router-active@dispatch.test",
            first_name="Active",
            source_type="manual",
        ),
        ip_address=None,
        user_agent=None,
    )
    unsubscribed = await auth_test_context.contact_service.create_contact(
        actor=actor,
        payload=ContactCreateRequest(
            email="segment-router-unsub@dispatch.test",
            first_name="Unsub",
            source_type="manual",
        ),
        ip_address=None,
        user_agent=None,
    )
    await auth_test_context.contact_service.unsubscribe_contact(
        actor=actor,
        contact_id=unsubscribed.id,
        reason="test",
        ip_address=None,
        user_agent=None,
    )

    login_response = await auth_client.post(
        "/auth/login",
        json={
            "email": "admin-segments-router@dispatch.test",
            "password": "correct-password-value",
        },
    )
    assert login_response.status_code == 200

    invalid_create = await auth_client.post(
        "/segments",
        json={
            "name": "Invalid segment",
            "description": None,
            "dsl_json": {"op": "eq", "field": "contact.password_hash", "value": "x"},
        },
    )
    assert invalid_create.status_code == 422

    create_response = await auth_client.post(
        "/segments",
        json={
            "name": "Dispatch domain segment",
            "description": "segment for router test",
            "dsl_json": {"op": "eq", "field": "contact.email_domain", "value": "dispatch.test"},
        },
    )
    assert create_response.status_code == 201
    created_payload = create_response.json()
    segment_id = created_payload["id"]
    assert created_payload["name"] == "Dispatch domain segment"
    assert created_payload["last_computed_count"] is None

    list_response = await auth_client.get("/segments")
    assert list_response.status_code == 200
    assert any(item["id"] == segment_id for item in list_response.json()["items"])

    get_response = await auth_client.get(f"/segments/{segment_id}")
    assert get_response.status_code == 200
    assert get_response.json()["dsl_json"]["field"] == "contact.email_domain"

    update_response = await auth_client.patch(
        f"/segments/{segment_id}",
        json={"name": "Updated segment name"},
    )
    assert update_response.status_code == 200
    assert update_response.json()["name"] == "Updated segment name"

    preview_response = await auth_client.post(f"/segments/{segment_id}/preview")
    assert preview_response.status_code == 200
    preview_payload = preview_response.json()
    assert preview_payload["total_count"] == 1
    assert len(preview_payload["sample"]) == 1
    assert preview_payload["sample"][0]["id"] == active.id

    evaluate_response = await auth_client.post(f"/segments/{segment_id}/evaluate")
    assert evaluate_response.status_code == 200
    evaluate_payload = evaluate_response.json()
    assert evaluate_payload["total_count"] == 1
    assert len(evaluate_payload["sample"]) == 1

    duplicate_response = await auth_client.post(f"/segments/{segment_id}/duplicate")
    assert duplicate_response.status_code == 200
    duplicate_payload = duplicate_response.json()
    duplicated_segment_id = duplicate_payload["id"]
    assert duplicated_segment_id != segment_id
    assert duplicate_payload["dsl_json"] == created_payload["dsl_json"]
    assert duplicate_payload["name"] == "Updated segment name (Copy)"

    delete_response = await auth_client.delete(f"/segments/{segment_id}")
    assert delete_response.status_code == 200

    deleted_get = await auth_client.get(f"/segments/{segment_id}")
    assert deleted_get.status_code == 404
