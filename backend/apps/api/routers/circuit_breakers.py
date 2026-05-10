from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field

from apps.api.deps import (
    get_circuit_breaker_service_dep,
    get_current_actor,
    require_admin,
)
from libs.core.auth.models import User
from libs.core.auth.schemas import CurrentActor, MessageResponse
from libs.core.circuit_breaker.service import CircuitBreakerService

router = APIRouter(prefix="/circuit-breakers", tags=["circuit_breakers"])


class CircuitBreakerItemResponse(BaseModel):
    id: str
    scope_type: str
    scope_id: str
    entity_name: str
    state: str
    tripped_at: datetime | None
    tripped_reason: str | None
    bounce_rate_pct: Decimal | None
    complaint_rate_pct: Decimal | None
    auto_reset_at: datetime | None
    reset_by: str | None
    reset_at: datetime | None
    updated_at: datetime


class CircuitBreakerListResponse(BaseModel):
    items: list[CircuitBreakerItemResponse]


class CircuitBreakerResetRequest(BaseModel):
    justification: str = Field(min_length=10, max_length=4000)


def _client_ip(request: Request) -> str | None:
    return request.client.host if request.client else None


@router.get("", response_model=CircuitBreakerListResponse)
async def list_circuit_breakers(
    _: Annotated[CurrentActor, Depends(get_current_actor)],
    __: Annotated[User, Depends(require_admin)],
    service: Annotated[CircuitBreakerService, Depends(get_circuit_breaker_service_dep)],
) -> CircuitBreakerListResponse:
    statuses = await service.list_breakers()
    return CircuitBreakerListResponse(
        items=[
            CircuitBreakerItemResponse(
                id=item.id,
                scope_type=item.scope_type,
                scope_id=item.scope_id,
                entity_name=item.entity_name,
                state=item.state,
                tripped_at=item.tripped_at,
                tripped_reason=item.tripped_reason,
                bounce_rate_pct=item.bounce_rate_24h,
                complaint_rate_pct=item.complaint_rate_24h,
                auto_reset_at=item.auto_reset_at,
                reset_by=item.reset_by,
                reset_at=item.reset_at,
                updated_at=item.updated_at,
            )
            for item in statuses
        ]
    )


@router.get("/scope/{scope_type}/{scope_id}", response_model=CircuitBreakerItemResponse)
async def get_circuit_breaker_status_by_scope(
    scope_type: str,
    scope_id: str,
    _: Annotated[CurrentActor, Depends(get_current_actor)],
    __: Annotated[User, Depends(require_admin)],
    service: Annotated[CircuitBreakerService, Depends(get_circuit_breaker_service_dep)],
) -> CircuitBreakerItemResponse:
    item = await service.get_breaker_status_by_scope(scope_type=scope_type, scope_id=scope_id)
    return CircuitBreakerItemResponse(
        id=item.id,
        scope_type=item.scope_type,
        scope_id=item.scope_id,
        entity_name=item.entity_name,
        state=item.state,
        tripped_at=item.tripped_at,
        tripped_reason=item.tripped_reason,
        bounce_rate_pct=item.bounce_rate_24h,
        complaint_rate_pct=item.complaint_rate_24h,
        auto_reset_at=item.auto_reset_at,
        reset_by=item.reset_by,
        reset_at=item.reset_at,
        updated_at=item.updated_at,
    )


@router.get("/{breaker_id}", response_model=CircuitBreakerItemResponse)
async def get_circuit_breaker_status(
    breaker_id: str,
    _: Annotated[CurrentActor, Depends(get_current_actor)],
    __: Annotated[User, Depends(require_admin)],
    service: Annotated[CircuitBreakerService, Depends(get_circuit_breaker_service_dep)],
) -> CircuitBreakerItemResponse:
    item = await service.get_breaker_status_by_id(breaker_id)
    return CircuitBreakerItemResponse(
        id=item.id,
        scope_type=item.scope_type,
        scope_id=item.scope_id,
        entity_name=item.entity_name,
        state=item.state,
        tripped_at=item.tripped_at,
        tripped_reason=item.tripped_reason,
        bounce_rate_pct=item.bounce_rate_24h,
        complaint_rate_pct=item.complaint_rate_24h,
        auto_reset_at=item.auto_reset_at,
        reset_by=item.reset_by,
        reset_at=item.reset_at,
        updated_at=item.updated_at,
    )


@router.post("/{breaker_id}/reset", response_model=MessageResponse)
async def reset_circuit_breaker(
    breaker_id: str,
    payload: CircuitBreakerResetRequest,
    request: Request,
    actor: Annotated[CurrentActor, Depends(get_current_actor)],
    _: Annotated[User, Depends(require_admin)],
    service: Annotated[CircuitBreakerService, Depends(get_circuit_breaker_service_dep)],
) -> MessageResponse:
    scope_type, scope_id = service.parse_breaker_id(breaker_id)
    await service.reset(
        scope_type=scope_type,
        scope_id=scope_id,
        actor_user_id=actor.user.id,
        reason=payload.justification,
        ip_address=_client_ip(request),
        user_agent=request.headers.get("user-agent"),
    )
    return MessageResponse(message="Circuit breaker reset")
