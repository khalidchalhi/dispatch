from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request, status

from apps.api.deps import get_campaign_service_dep, get_current_actor, require_admin
from libs.core.auth.models import User
from libs.core.auth.schemas import CurrentActor
from libs.core.campaigns.schemas import (
    CampaignCreateRequest,
    CampaignLaunchResponse,
    CampaignListResponse,
    CampaignMessageListItem,
    CampaignMessageListResponse,
    CampaignPreflightCheckResponse,
    CampaignPreflightResponse,
    CampaignResponse,
    CampaignStateChangeResponse,
    CampaignUpdateRequest,
    MessageSendResultResponse,
)
from libs.core.campaigns.service import CampaignService

router = APIRouter(prefix="/campaigns", tags=["campaigns"])


def _client_ip(request: Request) -> str | None:
    return request.client.host if request.client else None


@router.get("", response_model=CampaignListResponse)
async def list_campaigns(
    actor: Annotated[CurrentActor, Depends(get_current_actor)],
    _: Annotated[User, Depends(require_admin)],
    service: Annotated[CampaignService, Depends(get_campaign_service_dep)],
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
    status_filter: Annotated[str | None, Query(alias="status")] = None,
) -> CampaignListResponse:
    page = await service.list_campaigns(
        actor=actor,
        limit=limit,
        offset=offset,
        status=status_filter,
    )
    return CampaignListResponse(
        items=[CampaignResponse.from_model(item) for item in page.items],
        total=page.total,
        limit=page.limit,
        offset=page.offset,
    )


@router.post("", response_model=CampaignResponse, status_code=status.HTTP_201_CREATED)
async def create_campaign(
    payload: CampaignCreateRequest,
    request: Request,
    actor: Annotated[CurrentActor, Depends(get_current_actor)],
    _: Annotated[User, Depends(require_admin)],
    service: Annotated[CampaignService, Depends(get_campaign_service_dep)],
) -> CampaignResponse:
    created = await service.create_campaign(
        actor=actor,
        payload=payload,
        ip_address=_client_ip(request),
        user_agent=request.headers.get("user-agent"),
    )
    return CampaignResponse.from_model(created)


@router.get("/{campaign_id}", response_model=CampaignResponse)
async def get_campaign(
    campaign_id: str,
    actor: Annotated[CurrentActor, Depends(get_current_actor)],
    _: Annotated[User, Depends(require_admin)],
    service: Annotated[CampaignService, Depends(get_campaign_service_dep)],
) -> CampaignResponse:
    campaign = await service.get_campaign(actor=actor, campaign_id=campaign_id)
    return CampaignResponse.from_model(campaign)


@router.patch("/{campaign_id}", response_model=CampaignResponse)
async def update_campaign(
    campaign_id: str,
    payload: CampaignUpdateRequest,
    request: Request,
    actor: Annotated[CurrentActor, Depends(get_current_actor)],
    _: Annotated[User, Depends(require_admin)],
    service: Annotated[CampaignService, Depends(get_campaign_service_dep)],
) -> CampaignResponse:
    updated = await service.update_campaign(
        actor=actor,
        campaign_id=campaign_id,
        payload=payload,
        ip_address=_client_ip(request),
        user_agent=request.headers.get("user-agent"),
    )
    return CampaignResponse.from_model(updated)


@router.post("/{campaign_id}/preflight", response_model=CampaignPreflightResponse)
async def preflight_campaign(
    campaign_id: str,
    actor: Annotated[CurrentActor, Depends(get_current_actor)],
    _: Annotated[User, Depends(require_admin)],
    service: Annotated[CampaignService, Depends(get_campaign_service_dep)],
) -> CampaignPreflightResponse:
    result = await service.get_campaign_preflight(actor=actor, campaign_id=campaign_id)
    return CampaignPreflightResponse(
        campaign_id=result.campaign_id,
        checks=[
            CampaignPreflightCheckResponse(
                id=check.id,
                label=check.label,
                severity=check.severity,
                detail=check.detail,
            )
            for check in result.checks
        ],
        has_critical=any(check.severity == "critical" for check in result.checks),
        generated_at=result.generated_at,
    )


@router.get("/{campaign_id}/messages", response_model=CampaignMessageListResponse)
async def list_campaign_messages(
    campaign_id: str,
    actor: Annotated[CurrentActor, Depends(get_current_actor)],
    _: Annotated[User, Depends(require_admin)],
    service: Annotated[CampaignService, Depends(get_campaign_service_dep)],
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    cursor: Annotated[str | None, Query()] = None,
    status_filter: Annotated[str | None, Query(alias="status")] = None,
) -> CampaignMessageListResponse:
    page = await service.list_campaign_messages(
        actor=actor,
        campaign_id=campaign_id,
        limit=limit,
        cursor=cursor,
        status=status_filter,
    )
    return CampaignMessageListResponse(
        items=[
            CampaignMessageListItem(
                message_id=item.id,
                campaign_id=item.campaign_id,
                to_email=item.to_email,
                status=item.status,
                created_at=item.created_at,
                sent_at=item.sent_at,
                delivered_at=item.delivered_at,
                bounce_type=item.bounce_type,
                complaint_type=item.complaint_type,
                error_code=item.error_code,
                error_message=item.error_message,
                has_bounce=item.bounce_type is not None,
                has_click=item.first_clicked_at is not None,
                has_complaint=item.complaint_type is not None,
                ses_message_id=item.ses_message_id,
                last_event_at=(
                    item.delivered_at
                    or item.first_opened_at
                    or item.first_clicked_at
                    or item.replied_at
                    or item.sent_at
                    or item.created_at
                ),
            )
            for item in page.items
        ],
        next_cursor=page.next_cursor,
    )


@router.post(
    "/{campaign_id}/messages/{message_id}/requeue",
    response_model=MessageSendResultResponse,
)
async def requeue_campaign_message(
    campaign_id: str,
    message_id: str,
    request: Request,
    actor: Annotated[CurrentActor, Depends(get_current_actor)],
    _: Annotated[User, Depends(require_admin)],
    service: Annotated[CampaignService, Depends(get_campaign_service_dep)],
) -> MessageSendResultResponse:
    message = await service.requeue_campaign_message(
        actor=actor,
        campaign_id=campaign_id,
        message_id=message_id,
        ip_address=_client_ip(request),
        user_agent=request.headers.get("user-agent"),
    )
    return MessageSendResultResponse.from_model(message)


@router.post("/{campaign_id}/launch", response_model=CampaignLaunchResponse)
async def launch_campaign(
    campaign_id: str,
    request: Request,
    actor: Annotated[CurrentActor, Depends(get_current_actor)],
    _: Annotated[User, Depends(require_admin)],
    service: Annotated[CampaignService, Depends(get_campaign_service_dep)],
) -> CampaignLaunchResponse:
    result = await service.launch_campaign(
        actor=actor,
        campaign_id=campaign_id,
        ip_address=_client_ip(request),
        user_agent=request.headers.get("user-agent"),
    )
    return CampaignLaunchResponse.build(
        campaign=result.campaign,
        campaign_run=result.campaign_run,
        snapshot_rows=result.snapshot_rows,
        created_messages=result.created_messages,
        enqueued_messages=result.enqueued_messages,
        already_launched=result.already_launched,
    )


@router.post("/{campaign_id}/pause", response_model=CampaignStateChangeResponse)
async def pause_campaign(
    campaign_id: str,
    request: Request,
    actor: Annotated[CurrentActor, Depends(get_current_actor)],
    _: Annotated[User, Depends(require_admin)],
    service: Annotated[CampaignService, Depends(get_campaign_service_dep)],
) -> CampaignStateChangeResponse:
    result = await service.pause_campaign(
        actor=actor,
        campaign_id=campaign_id,
        ip_address=_client_ip(request),
        user_agent=request.headers.get("user-agent"),
    )
    return CampaignStateChangeResponse(
        campaign=CampaignResponse.from_model(result.campaign),
    )


@router.post("/{campaign_id}/resume", response_model=CampaignStateChangeResponse)
async def resume_campaign(
    campaign_id: str,
    request: Request,
    actor: Annotated[CurrentActor, Depends(get_current_actor)],
    _: Annotated[User, Depends(require_admin)],
    service: Annotated[CampaignService, Depends(get_campaign_service_dep)],
) -> CampaignStateChangeResponse:
    result = await service.resume_campaign(
        actor=actor,
        campaign_id=campaign_id,
        ip_address=_client_ip(request),
        user_agent=request.headers.get("user-agent"),
    )
    return CampaignStateChangeResponse(
        campaign=CampaignResponse.from_model(result.campaign),
        enqueued_messages=result.enqueued_messages,
    )


@router.post("/{campaign_id}/cancel", response_model=CampaignStateChangeResponse)
async def cancel_campaign(
    campaign_id: str,
    request: Request,
    actor: Annotated[CurrentActor, Depends(get_current_actor)],
    _: Annotated[User, Depends(require_admin)],
    service: Annotated[CampaignService, Depends(get_campaign_service_dep)],
) -> CampaignStateChangeResponse:
    result = await service.cancel_campaign(
        actor=actor,
        campaign_id=campaign_id,
        ip_address=_client_ip(request),
        user_agent=request.headers.get("user-agent"),
    )
    return CampaignStateChangeResponse(
        campaign=CampaignResponse.from_model(result.campaign),
        cancelled_queued_messages=result.cancelled_queued_messages,
    )
