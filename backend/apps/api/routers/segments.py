from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Request, status

from apps.api.deps import get_current_actor, get_segment_service_dep, require_admin
from libs.core.auth.models import User
from libs.core.auth.schemas import CurrentActor, MessageResponse
from libs.core.segments.schemas import (
    SegmentContactSampleResponse,
    SegmentCreateRequest,
    SegmentListResponse,
    SegmentPreviewResponse,
    SegmentResponse,
    SegmentUpdateRequest,
)
from libs.core.segments.service import SegmentService

router = APIRouter(prefix="/segments", tags=["segments"])


def _client_ip(request: Request) -> str | None:
    return request.client.host if request.client else None


@router.post("", response_model=SegmentResponse, status_code=status.HTTP_201_CREATED)
async def create_segment(
    payload: SegmentCreateRequest,
    request: Request,
    actor: Annotated[CurrentActor, Depends(get_current_actor)],
    _: Annotated[User, Depends(require_admin)],
    service: Annotated[SegmentService, Depends(get_segment_service_dep)],
) -> SegmentResponse:
    created = await service.create_segment(
        actor=actor,
        payload=payload,
        ip_address=_client_ip(request),
        user_agent=request.headers.get("user-agent"),
    )
    return SegmentResponse.from_model(
        created.segment,
        description=created.description,
    )


@router.get("", response_model=SegmentListResponse)
async def list_segments(
    actor: Annotated[CurrentActor, Depends(get_current_actor)],
    _: Annotated[User, Depends(require_admin)],
    service: Annotated[SegmentService, Depends(get_segment_service_dep)],
) -> SegmentListResponse:
    records = await service.list_segments(actor=actor)
    return SegmentListResponse(
        items=[
            SegmentResponse.from_model(
                record.segment,
                description=record.description,
            )
            for record in records
        ]
    )


@router.get("/{segment_id}", response_model=SegmentResponse)
async def get_segment(
    segment_id: str,
    actor: Annotated[CurrentActor, Depends(get_current_actor)],
    _: Annotated[User, Depends(require_admin)],
    service: Annotated[SegmentService, Depends(get_segment_service_dep)],
) -> SegmentResponse:
    record = await service.get_segment(actor=actor, segment_id=segment_id)
    return SegmentResponse.from_model(
        record.segment,
        description=record.description,
    )


@router.patch("/{segment_id}", response_model=SegmentResponse)
async def update_segment(
    segment_id: str,
    payload: SegmentUpdateRequest,
    request: Request,
    actor: Annotated[CurrentActor, Depends(get_current_actor)],
    _: Annotated[User, Depends(require_admin)],
    service: Annotated[SegmentService, Depends(get_segment_service_dep)],
) -> SegmentResponse:
    updated = await service.update_segment(
        actor=actor,
        segment_id=segment_id,
        payload=payload,
        ip_address=_client_ip(request),
        user_agent=request.headers.get("user-agent"),
    )
    return SegmentResponse.from_model(
        updated.segment,
        description=updated.description,
    )


@router.delete("/{segment_id}", response_model=MessageResponse)
async def delete_segment(
    segment_id: str,
    request: Request,
    actor: Annotated[CurrentActor, Depends(get_current_actor)],
    _: Annotated[User, Depends(require_admin)],
    service: Annotated[SegmentService, Depends(get_segment_service_dep)],
) -> MessageResponse:
    await service.delete_segment(
        actor=actor,
        segment_id=segment_id,
        ip_address=_client_ip(request),
        user_agent=request.headers.get("user-agent"),
    )
    return MessageResponse(message="Segment soft-deleted")


@router.post("/{segment_id}/preview", response_model=SegmentPreviewResponse)
@router.post("/{segment_id}/evaluate", response_model=SegmentPreviewResponse)
async def evaluate_segment(
    segment_id: str,
    actor: Annotated[CurrentActor, Depends(get_current_actor)],
    _: Annotated[User, Depends(require_admin)],
    service: Annotated[SegmentService, Depends(get_segment_service_dep)],
) -> SegmentPreviewResponse:
    preview = await service.preview_segment(actor=actor, segment_id=segment_id)
    return SegmentPreviewResponse(
        total_count=preview.total_count,
        sample=[SegmentContactSampleResponse.from_model(contact) for contact in preview.sample],
    )


@router.post("/{segment_id}/duplicate", response_model=SegmentResponse)
async def duplicate_segment(
    segment_id: str,
    request: Request,
    actor: Annotated[CurrentActor, Depends(get_current_actor)],
    _: Annotated[User, Depends(require_admin)],
    service: Annotated[SegmentService, Depends(get_segment_service_dep)],
) -> SegmentResponse:
    duplicated = await service.duplicate_segment(
        actor=actor,
        segment_id=segment_id,
        ip_address=_client_ip(request),
        user_agent=request.headers.get("user-agent"),
    )
    return SegmentResponse.from_model(
        duplicated.segment,
        description=duplicated.description,
    )
