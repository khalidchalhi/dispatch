from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

from apps.workers import send_tasks
from apps.workers.queues import SendTaskRouter, queue_name_for_domain
from libs.core.campaigns.service import MessageSendResult, SendMessageDispatchContext
from libs.core.throttle.token_bucket import TokenBucketDecision
from tests.integration.workers.test_send_tasks import _create_admin_actor, _prepare_campaign

AuthTestContext = Any
UserFactory = Any


def test_send_task_router_uses_domain_name_and_domain_id_cache() -> None:
    router = SendTaskRouter()

    first = router(
        "send.send_message",
        (),
        {"message_id": "msg-1", "domain_id": "domain-1", "domain_name": "Acme.EXAMPLE.com"},
        {},
    )
    second = router(
        "send.send_message",
        (),
        {"message_id": "msg-2", "domain_id": "domain-1"},
        {},
    )

    assert first is not None
    assert first["queue"] == "send.acme.example.com"
    assert first["routing_key"] == "send.acme.example.com"

    assert second is not None
    assert second["queue"] == "send.acme.example.com"


def test_queue_name_for_domain_sanitizes_value() -> None:
    assert queue_name_for_domain("  SALES+EU.EXAMPLE.com ") == "send.sales-eu.example.com"


def test_send_task_router_resolves_domain_name_from_domain_id() -> None:
    @dataclass(slots=True)
    class _StubResolver:
        lookup_count: int = 0

        def resolve(self, domain_id: str) -> str | None:
            self.lookup_count += 1
            if domain_id == "domain-2":
                return "Beta.EXAMPLE.com"
            return None

    resolver = _StubResolver()
    router = SendTaskRouter(_resolver=resolver)

    first = router("send.send_message", (), {"message_id": "msg-1", "domain_id": "domain-2"}, {})
    second = router("send.send_message", (), {"message_id": "msg-2", "domain_id": "domain-2"}, {})

    assert first is not None
    assert first["queue"] == "send.beta.example.com"
    assert second is not None
    assert second["queue"] == "send.beta.example.com"
    assert resolver.lookup_count == 1


def test_campaign_launch_enqueues_routing_context(
    auth_test_context: AuthTestContext,
    auth_user_factory: UserFactory,
    monkeypatch: Any,
) -> None:
    from apps.workers import celery_app as celery_module

    actor = asyncio.run(_create_admin_actor(auth_user_factory))
    campaign_id, service, _ = asyncio.run(
        _prepare_campaign(auth_test_context=auth_test_context, actor=actor)
    )

    captured: list[dict[str, object]] = []

    def _capture_send_task(task_name: str, kwargs: dict[str, object], **options: object) -> None:
        assert task_name == "send.send_message"
        _ = options
        captured.append(kwargs)

    monkeypatch.setattr(celery_module.celery_app, "send_task", _capture_send_task)

    launch = asyncio.run(
        service.launch_campaign(
            actor=actor,
            campaign_id=campaign_id,
            ip_address=None,
            user_agent=None,
        )
    )

    assert launch.enqueued_messages == 1
    assert len(captured) == 1
    assert captured[0]["message_id"]
    assert captured[0]["domain_id"]
    assert captured[0]["domain_name"]


def test_send_task_requeues_on_domain_rate_limit(monkeypatch: Any) -> None:
    from apps.workers import celery_app as celery_module

    class _StubCampaignService:
        async def get_send_message_dispatch_context(self, *, message_id: str) -> None:
            _ = message_id
            return None

        async def send_queued_message(self, *, message_id: str) -> MessageSendResult:
            return MessageSendResult(
                message_id=message_id,
                status="queued",
                error_code="rate_limited_domain",
                error_message="Domain hourly send limit reached; message re-queued for retry",
                retry_after_seconds=17,
                domain_id="domain-1",
                domain_name="alpha.example.com",
            )

    captured: list[tuple[str, dict[str, object], int]] = []

    def _capture_send_task(task_name: str, kwargs: dict[str, object], **options: object) -> None:
        raw_countdown = options.get("countdown", 0)
        countdown = raw_countdown if isinstance(raw_countdown, int) else 0
        captured.append((task_name, kwargs, countdown))

    monkeypatch.setattr(send_tasks, "get_campaign_service", lambda: _StubCampaignService())
    monkeypatch.setattr(celery_module.celery_app, "send_task", _capture_send_task)

    result = send_tasks.send_message("msg-1", "domain-1", "alpha.example.com")

    assert result["status"] == "queued"
    assert result["error_code"] == "rate_limited_domain"
    assert len(captured) == 1
    assert captured[0][0] == "send.send_message"
    assert captured[0][1]["message_id"] == "msg-1"
    assert captured[0][1]["domain_id"] == "domain-1"
    assert captured[0][1]["domain_name"] == "alpha.example.com"
    assert captured[0][2] == 17


def test_send_task_applies_bucket_before_service_send(monkeypatch: Any) -> None:
    from apps.workers import celery_app as celery_module

    class _StubCampaignService:
        async def get_send_message_dispatch_context(
            self, *, message_id: str
        ) -> SendMessageDispatchContext:
            return SendMessageDispatchContext(
                message_id=message_id,
                status="queued",
                error_code=None,
                domain_id="domain-3",
                domain_name="gamma.example.com",
                domain_rate_limit_per_hour=1,
            )

        async def send_queued_message(self, *, message_id: str) -> MessageSendResult:
            return MessageSendResult(
                message_id=message_id,
                status="sent",
                domain_id="domain-3",
                domain_name="gamma.example.com",
            )

    class _StubTokenBucket:
        async def try_take(
            self,
            *,
            domain_id: str,
            capacity_per_hour: int,
            requested_tokens: int = 1,
        ) -> TokenBucketDecision:
            _ = (domain_id, capacity_per_hour, requested_tokens)
            return TokenBucketDecision(
                allowed=False,
                retry_after_seconds=9,
                tokens_remaining=0,
            )

    captured: list[tuple[str, dict[str, object], int]] = []

    def _capture_send_task(task_name: str, kwargs: dict[str, object], **options: object) -> None:
        raw_countdown = options.get("countdown", 0)
        countdown = raw_countdown if isinstance(raw_countdown, int) else 0
        captured.append((task_name, kwargs, countdown))

    monkeypatch.setattr(send_tasks, "get_campaign_service", lambda: _StubCampaignService())
    monkeypatch.setattr(send_tasks, "get_domain_token_bucket", lambda: _StubTokenBucket())
    monkeypatch.setattr(celery_module.celery_app, "send_task", _capture_send_task)

    result = send_tasks.send_message("msg-3")

    assert result["status"] == "queued"
    assert result["error_code"] == "rate_limited_domain"
    assert result["retry_after_seconds"] == 9
    assert result["domain_id"] == "domain-3"
    assert result["domain_name"] == "gamma.example.com"
    assert len(captured) == 1
    assert captured[0][0] == "send.send_message"
    assert captured[0][1]["message_id"] == "msg-3"
    assert captured[0][2] == 9
