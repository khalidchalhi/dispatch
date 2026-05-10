from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from apps.api.deps import (
    get_auth_service_dep,
    get_campaign_service_dep,
    get_settings_dep,
    get_user_service_dep,
)
from apps.api.main import app
from libs.core.auth.schemas import CurrentActor
from libs.core.campaigns.models import Message
from libs.core.campaigns.service import CampaignService
from libs.core.db.uow import UnitOfWork
from libs.core.domains.schemas import DnsRecordType
from libs.core.segments.schemas import SegmentCreateRequest
from libs.core.sender_profiles.schemas import SenderProfileCreateRequest
from libs.core.templates.schemas import TemplateCreateRequest

AuthTestContext = Any
UserFactory = Any


@pytest.fixture
async def auth_client(auth_test_context: AuthTestContext) -> AsyncIterator[AsyncClient]:
    app.dependency_overrides[get_settings_dep] = lambda: auth_test_context.settings
    app.dependency_overrides[get_auth_service_dep] = lambda: auth_test_context.auth_service
    app.dependency_overrides[get_user_service_dep] = lambda: auth_test_context.user_service
    app.dependency_overrides[get_campaign_service_dep] = lambda: CampaignService(
        auth_test_context.settings,
        segment_service=auth_test_context.segment_service,
    )
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client
    app.dependency_overrides.clear()


async def _login_admin(client: AsyncClient, auth_user_factory: UserFactory) -> CurrentActor:
    email = f"campaigns-router-admin-{uuid4().hex[:8]}@dispatch.test"
    password = "router-password-value"
    user = await auth_user_factory(email=email, password=password, role="admin")
    response = await client.post("/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200
    return CurrentActor(actor_type="user", user=user)


async def _seed_campaign_dependencies(
    *,
    auth_test_context: AuthTestContext,
    actor: CurrentActor,
) -> dict[str, str | int]:
    domain_name = f"campaigns-router-{uuid4().hex[:8]}.dispatch.test"
    domain_detail = await auth_test_context.domain_service.create_domain(
        actor=actor,
        name=domain_name,
        dns_provider="manual",
        parent_domain="dispatch.test",
        ses_region="us-east-1",
        default_configuration_set_name=None,
        event_destination_sns_topic_arn=None,
        ip_address=None,
        user_agent=None,
    )
    for record in domain_detail.dns_records:
        auth_test_context.dns_adapter.set_record(
            record_type=DnsRecordType(record.record_type),
            name=record.name,
            values=[record.value],
        )
    await auth_test_context.domain_service.verify_domain(
        actor=actor,
        domain_id=domain_detail.domain.id,
        ip_address=None,
        user_agent=None,
    )

    sender_profile = await auth_test_context.sender_profile_service.create_sender_profile(
        actor=actor,
        payload=SenderProfileCreateRequest(
            display_name="Router Sender",
            from_name="Dispatch",
            from_email=f"sender@{domain_name}",
            reply_to=None,
            domain_id=domain_detail.domain.id,
            configuration_set_id=None,
            ip_pool_id=None,
            allowed_campaign_types=["outreach"],
            daily_send_limit=2000,
        ),
        ip_address=None,
        user_agent=None,
    )

    template = await auth_test_context.template_service.create_template(
        actor=actor,
        payload=TemplateCreateRequest(
            name="Router Template",
            description=None,
            category="outreach",
            subject="Hello {{contact.first_name}}",
            body_text="Body",
            body_html="<p>Body</p>",
            spintax_enabled=False,
        ),
        ip_address=None,
        user_agent=None,
    )
    version = template.versions[0]

    segment = await auth_test_context.segment_service.create_segment(
        actor=actor,
        payload=SegmentCreateRequest(
            name="Router Segment",
            description=None,
            dsl_json={"op": "contains", "field": "contact.email", "value": "@"},
        ),
        ip_address=None,
        user_agent=None,
    )

    return {
        "domain_id": domain_detail.domain.id,
        "sender_profile_id": sender_profile.id,
        "template_id": template.template.id,
        "template_version": version.version_number,
        "template_version_id": version.id,
        "segment_id": segment.segment.id,
    }


@pytest.mark.asyncio
async def test_campaign_crud_and_preflight_routes(
    auth_client: AsyncClient,
    auth_test_context: AuthTestContext,
    auth_user_factory: UserFactory,
) -> None:
    actor = await _login_admin(auth_client, auth_user_factory)
    deps = await _seed_campaign_dependencies(auth_test_context=auth_test_context, actor=actor)

    create_response = await auth_client.post(
        "/campaigns",
        json={
            "name": "Router CRUD Campaign",
            "campaignType": "outreach",
            "senderProfileId": deps["sender_profile_id"],
            "templateId": deps["template_id"],
            "templateVersion": deps["template_version"],
            "audienceType": "segment",
            "audienceId": deps["segment_id"],
            "scheduleType": "immediate",
            "timezone": "UTC",
        },
    )
    assert create_response.status_code == 201
    created = create_response.json()
    campaign_id = created["id"]
    assert created["name"] == "Router CRUD Campaign"

    list_response = await auth_client.get("/campaigns?limit=50&offset=0")
    assert list_response.status_code == 200
    list_payload = list_response.json()
    assert list_payload["total"] >= 1
    assert any(item["id"] == campaign_id for item in list_payload["items"])

    get_response = await auth_client.get(f"/campaigns/{campaign_id}")
    assert get_response.status_code == 200
    assert get_response.json()["id"] == campaign_id

    patch_response = await auth_client.patch(
        f"/campaigns/{campaign_id}",
        json={"name": "Router CRUD Campaign Updated", "sendRatePerHour": 250},
    )
    assert patch_response.status_code == 200
    patched = patch_response.json()
    assert patched["name"] == "Router CRUD Campaign Updated"
    assert patched["send_rate_per_hour"] == 250

    preflight_response = await auth_client.post(f"/campaigns/{campaign_id}/preflight")
    assert preflight_response.status_code == 200
    preflight = preflight_response.json()
    assert preflight["campaign_id"] == campaign_id
    assert isinstance(preflight["checks"], list)
    assert "has_critical" in preflight


@pytest.mark.asyncio
async def test_campaign_messages_and_requeue_routes(
    auth_client: AsyncClient,
    auth_test_context: AuthTestContext,
    auth_user_factory: UserFactory,
) -> None:
    actor = await _login_admin(auth_client, auth_user_factory)
    deps = await _seed_campaign_dependencies(auth_test_context=auth_test_context, actor=actor)

    create_response = await auth_client.post(
        "/campaigns",
        json={
            "name": "Router Messages Campaign",
            "campaignType": "outreach",
            "senderProfileId": deps["sender_profile_id"],
            "templateVersionId": deps["template_version_id"],
            "segmentId": deps["segment_id"],
            "scheduleType": "immediate",
            "timezone": "UTC",
        },
    )
    assert create_response.status_code == 201
    campaign = create_response.json()
    campaign_id = campaign["id"]

    async with UnitOfWork(auth_test_context.session_factory) as uow:
        message = Message(
            campaign_id=campaign_id,
            send_batch_id=None,
            contact_id=None,
            sender_profile_id=str(deps["sender_profile_id"]),
            domain_id=str(deps["domain_id"]),
            to_email="failed@dispatch.test",
            from_email="sender@dispatch.test",
            subject="Failed message",
            status="failed",
            headers={},
            error_code="seeded_failure",
            error_message="seeded failure",
        )
        uow.require_session().add(message)
        await uow.require_session().flush()
        failed_message_id = message.id

    list_response = await auth_client.get(
        f"/campaigns/{campaign_id}/messages?limit=20"
    )
    assert list_response.status_code == 200
    list_payload = list_response.json()
    assert len(list_payload["items"]) >= 1
    assert any(item["message_id"] == failed_message_id for item in list_payload["items"])

    requeue_response = await auth_client.post(
        f"/campaigns/{campaign_id}/messages/{failed_message_id}/requeue"
    )
    assert requeue_response.status_code == 200
    requeued = requeue_response.json()
    assert requeued["status"] == "queued"
    assert requeued["message_id"] != failed_message_id
