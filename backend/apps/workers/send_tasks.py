from __future__ import annotations

import asyncio
from collections.abc import Coroutine
from typing import Any

from apps.workers.celery_app import celery_app
from libs.core.campaigns.service import MessageSendResult, get_campaign_service
from libs.core.throttle.token_bucket import get_domain_token_bucket
from libs.ses_client.errors import SesTransientError


def _run_async[T](awaitable: Coroutine[Any, Any, T]) -> T:
    return asyncio.run(awaitable)


@celery_app.task(  # type: ignore[untyped-decorator]
    name="send.send_message",
    autoretry_for=(SesTransientError,),
    retry_backoff=True,
    retry_jitter=True,
    retry_kwargs={"max_retries": 3},
)
def send_message(
    message_id: str,
    domain_id: str | None = None,
    domain_name: str | None = None,
) -> dict[str, Any]:
    campaign_service = get_campaign_service()
    token_bucket = get_domain_token_bucket()

    dispatch_context = _run_async(
        campaign_service.get_send_message_dispatch_context(message_id=message_id)
    )
    effective_domain_id = dispatch_context.domain_id if dispatch_context is not None else domain_id
    effective_domain_name = (
        dispatch_context.domain_name if dispatch_context is not None else domain_name
    )
    should_apply_hourly_bucket = (
        dispatch_context is not None
        and dispatch_context.status in {"queued", "paused"}
        and not (
            dispatch_context.status == "paused"
            and dispatch_context.error_code != "circuit_open"
        )
    )

    if should_apply_hourly_bucket:
        throttle = _run_async(
            token_bucket.try_take(
                domain_id=dispatch_context.domain_id,
                capacity_per_hour=dispatch_context.domain_rate_limit_per_hour,
                requested_tokens=1,
            )
        )
        if not throttle.allowed:
            retry_after = max(throttle.retry_after_seconds, 1)
            next_kwargs: dict[str, str] = {"message_id": message_id}
            if effective_domain_id:
                next_kwargs["domain_id"] = effective_domain_id
            if effective_domain_name:
                next_kwargs["domain_name"] = effective_domain_name

            celery_app.send_task(
                "send.send_message",
                kwargs=next_kwargs,
                countdown=retry_after,
            )
            return {
                "message_id": message_id,
                "status": "queued",
                "ses_message_id": None,
                "error_code": "rate_limited_domain",
                "error_message": "Domain hourly send limit reached; message re-queued for retry",
                "retry_after_seconds": retry_after,
                "domain_id": effective_domain_id,
                "domain_name": effective_domain_name,
            }

    result: MessageSendResult = _run_async(
        campaign_service.send_queued_message(message_id=message_id),
    )

    retry_after = result.retry_after_seconds
    if result.error_code in {"rate_limited_domain", "circuit_open"} and retry_after is not None:
        next_kwargs: dict[str, str] = {"message_id": result.message_id}
        effective_domain_id = result.domain_id or effective_domain_id
        effective_domain_name = result.domain_name or effective_domain_name
        if effective_domain_id:
            next_kwargs["domain_id"] = effective_domain_id
        if effective_domain_name:
            next_kwargs["domain_name"] = effective_domain_name

        celery_app.send_task(
            "send.send_message",
            kwargs=next_kwargs,
            countdown=max(retry_after, 1),
        )

    return {
        "message_id": result.message_id,
        "status": result.status,
        "ses_message_id": result.ses_message_id,
        "error_code": result.error_code,
        "error_message": result.error_message,
        "retry_after_seconds": result.retry_after_seconds,
        "domain_id": result.domain_id or effective_domain_id,
        "domain_name": result.domain_name or effective_domain_name,
    }
