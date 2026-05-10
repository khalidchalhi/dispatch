from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient

from apps.api.deps import (
    get_auth_service_dep,
    get_settings_dep,
    get_template_service_dep,
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
    app.dependency_overrides[get_template_service_dep] = lambda: auth_test_context.template_service
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client
    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_templates_router_full_flow(
    auth_client: AsyncClient,
    auth_user_factory: UserFactory,
) -> None:
    await auth_user_factory(
        email="admin-templates-router@dispatch.test",
        password="correct-password-value",
        role="admin",
    )
    login_response = await auth_client.post(
        "/auth/login",
        json={
            "email": "admin-templates-router@dispatch.test",
            "password": "correct-password-value",
        },
    )
    assert login_response.status_code == 200

    create_response = await auth_client.post(
        "/templates",
        json={
            "name": "Starter template",
            "description": "First version",
            "category": "marketing",
            "subject": "Hello {{contact.first_name}}",
            "body_text": "Plan: {{contact.preferences.plan}}",
            "body_html": "<p>Hello {{contact.first_name}}</p>",
            "spintax_enabled": True,
        },
    )
    assert create_response.status_code == 201
    created_payload = create_response.json()
    template_id = created_payload["id"]
    assert created_payload["head_version_number"] == 1
    assert created_payload["is_archived"] is False
    assert created_payload["versions"][0]["merge_tags"] == [
        "contact.first_name",
        "contact.preferences.plan",
    ]
    merge_tags_response = await auth_client.get("/templates/merge-tags")
    assert merge_tags_response.status_code == 200
    merge_tags_payload = merge_tags_response.json()
    assert any(item["tag"] == "{{contact.first_name}}" for item in merge_tags_payload)
    assert any(item["tag"] == "{{contact.unsubscribe_url}}" for item in merge_tags_payload)

    version_response = await auth_client.post(
        f"/templates/{template_id}/versions",
        json={
            "subject": "مرحبا {{contact.first_name}}",
            "body_text": "Dear {{contact.first_name}} {{contact.last_name}}",
            "body_html": None,
            "spintax_enabled": False,
        },
    )
    assert version_response.status_code == 200
    version_payload = version_response.json()
    assert version_payload["head_version_number"] == 2
    assert len(version_payload["versions"]) == 2
    assert version_payload["versions"][1]["is_published"] is True
    assert version_payload["versions"][0]["is_published"] is False
    publish_response = await auth_client.post(
        f"/templates/{template_id}/versions/1/publish",
    )
    assert publish_response.status_code == 200
    publish_payload = publish_response.json()
    assert publish_payload["head_version_number"] == 1
    assert publish_payload["versions"][0]["is_published"] is True
    assert publish_payload["versions"][1]["is_published"] is False

    list_response = await auth_client.get("/templates")
    assert list_response.status_code == 200
    list_items = list_response.json()["items"]
    assert any(
        item["id"] == template_id and item["head_version_number"] == 1
        for item in list_items
    )

    get_template_response = await auth_client.get(f"/templates/{template_id}")
    assert get_template_response.status_code == 200
    assert len(get_template_response.json()["versions"]) == 2

    get_version_response = await auth_client.get(f"/templates/{template_id}/versions/1")
    assert get_version_response.status_code == 200
    assert get_version_response.json()["version_number"] == 1

    immutable_update = await auth_client.patch(
        f"/templates/{template_id}/versions/1",
        json={"subject": "attempted update"},
    )
    assert immutable_update.status_code == 409
    assert immutable_update.json()["error"]["code"] == "conflict"

    preview_response = await auth_client.post(
        f"/templates/{template_id}/preview",
        json={
            "version_number": 2,
            "sample_contact": {
                "first_name": "خالد",
                "last_name": "Coder",
                "preferences": {"plan": "Pro"},
            },
        },
    )
    assert preview_response.status_code == 200
    preview_payload = preview_response.json()
    assert preview_payload["rendered_subject"] == "مرحبا خالد"
    assert preview_payload["rendered_body_text"] == "Dear خالد Coder"

    archive_response = await auth_client.post(f"/templates/{template_id}/archive")
    assert archive_response.status_code == 200
    assert archive_response.json()["is_archived"] is True
    assert archive_response.json()["category"] == "marketing"

    blocked_version_response = await auth_client.post(
        f"/templates/{template_id}/versions",
        json={
            "subject": "Blocked",
            "body_text": "This should fail",
            "body_html": None,
            "spintax_enabled": False,
        },
    )
    assert blocked_version_response.status_code == 409

    dangerous_response = await auth_client.post(
        "/templates",
        json={
            "name": "dangerous-template",
            "description": None,
            "category": None,
            "subject": "{{ contact.__class__ }}",
            "body_text": "x",
            "body_html": None,
            "spintax_enabled": False,
        },
    )
    assert dangerous_response.status_code == 422
