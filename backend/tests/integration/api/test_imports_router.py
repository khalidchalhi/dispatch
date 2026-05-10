from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient

from apps.api.deps import (
    get_auth_service_dep,
    get_import_service_dep,
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
    app.dependency_overrides[get_import_service_dep] = lambda: auth_test_context.import_service
    app.dependency_overrides[get_suppression_service_dep] = (
        lambda: auth_test_context.suppression_service
    )
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client
    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_imports_router_create_and_get_status(
    auth_client: AsyncClient,
    auth_test_context: AuthTestContext,
    auth_user_factory: UserFactory,
) -> None:
    await auth_user_factory(
        email="admin-imports-router@dispatch.test",
        password="correct-password-value",
        role="admin",
    )
    login_response = await auth_client.post(
        "/auth/login",
        json={
            "email": "admin-imports-router@dispatch.test",
            "password": "correct-password-value",
        },
    )
    assert login_response.status_code == 200

    auth_test_context.mx_lookup.set_result(domain="good.com", has_mx=True)
    auth_test_context.mx_lookup.set_result(domain="nomx.test", has_mx=False)

    csv_content = (
        "email,first_name,last_name\n"
        "valid@good.com,Valid,One\n"
        "invalid-email,Bad,Format\n"
        "nomx@nomx.test,No,Mx\n"
        "info@good.com,Role,Account\n"
        "valid@good.com,Dupe,Row\n"
    )
    create_response = await auth_client.post(
        "/imports",
        files={"file": ("contacts.csv", csv_content, "text/csv")},
        data={"source_label": "integration"},
    )
    assert create_response.status_code == 201
    create_payload = create_response.json()
    job_id = create_payload["id"]
    assert create_payload["status"] == "queued"

    queued_status = await auth_client.get(f"/imports/{job_id}")
    assert queued_status.status_code == 200
    assert queued_status.json()["status"] == "queued"

    await auth_test_context.import_service.run_import_job(job_id=job_id)

    complete_status = await auth_client.get(f"/imports/{job_id}")
    assert complete_status.status_code == 200
    payload = complete_status.json()
    assert payload["status"] == "complete"
    assert payload["total_rows"] == 5
    assert payload["valid_rows"] == 1
    assert payload["invalid_rows"] == 2
    assert payload["suppressed_rows"] == 1
    assert payload["duplicate_rows"] == 1
    assert len(payload["sample_error_rows"]) >= 3


@pytest.mark.asyncio
async def test_contacts_bulk_import_route_aliases(
    auth_client: AsyncClient,
    auth_test_context: AuthTestContext,
    auth_user_factory: UserFactory,
) -> None:
    await auth_user_factory(
        email="admin-contacts-import-alias@dispatch.test",
        password="correct-password-value",
        role="admin",
    )
    login_response = await auth_client.post(
        "/auth/login",
        json={
            "email": "admin-contacts-import-alias@dispatch.test",
            "password": "correct-password-value",
        },
    )
    assert login_response.status_code == 200

    auth_test_context.mx_lookup.set_result(domain="good.com", has_mx=True)
    csv_content = "email,first_name\nvalid@good.com,Valid\ninvalid-email,Bad\n"

    create_response = await auth_client.post(
        "/contacts/bulk-import",
        files={"file": ("contacts.csv", csv_content, "text/csv")},
    )
    assert create_response.status_code == 201
    job_id = create_response.json()["id"]

    await auth_test_context.import_service.run_import_job(job_id=job_id)

    by_id_response = await auth_client.get(f"/contacts/bulk-import/{job_id}")
    assert by_id_response.status_code == 200
    by_id_payload = by_id_response.json()
    assert by_id_payload["id"] == job_id
    assert by_id_payload["status"] == "complete"

    status_response = await auth_client.get(f"/contacts/bulk-import/{job_id}/status")
    assert status_response.status_code == 200
    status_payload = status_response.json()
    assert status_payload["id"] == job_id
    assert status_payload["status"] == "complete"

    errors_response = await auth_client.get(f"/contacts/bulk-import/{job_id}/errors")
    assert errors_response.status_code == 200
    errors_payload = errors_response.json()
    assert isinstance(errors_payload, list)
    assert len(errors_payload) >= 1


@pytest.mark.asyncio
async def test_contacts_bulk_unsubscribe_from_csv(
    auth_client: AsyncClient,
    auth_user_factory: UserFactory,
) -> None:
    await auth_user_factory(
        email="admin-contacts-bulk-unsub@dispatch.test",
        password="correct-password-value",
        role="admin",
    )
    login_response = await auth_client.post(
        "/auth/login",
        json={
            "email": "admin-contacts-bulk-unsub@dispatch.test",
            "password": "correct-password-value",
        },
    )
    assert login_response.status_code == 200

    payload = "email\none@example.com\ntwo@example.com\nbad-email\n"
    bulk_response = await auth_client.post(
        "/contacts/bulk-unsubscribe",
        content=payload,
        headers={"content-type": "text/csv"},
    )
    assert bulk_response.status_code == 200
    result = bulk_response.json()
    assert result["total_rows"] == 3
    assert result["imported_count"] == 2
    assert result["invalid_count"] == 1

    get_suppressed = await auth_client.get("/suppression/one%40example.com")
    assert get_suppressed.status_code == 200
    suppressed_payload = get_suppressed.json()
    assert suppressed_payload["reason_code"] == "unsubscribe"
