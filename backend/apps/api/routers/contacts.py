from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request, status

from apps.api.deps import (
    get_contact_service_dep,
    get_current_actor,
    get_settings_dep,
    require_admin,
)
from libs.core.auth.models import User
from libs.core.auth.schemas import CurrentActor, MessageResponse
from libs.core.config import Settings
from libs.core.contacts.schemas import (
    ContactCreateRequest,
    ContactDeleteRequest,
    ContactLifecycleStatus,
    ContactListResponse,
    ContactPreferenceResponse,
    ContactPreferenceUpdateRequest,
    ContactQueryParams,
    ContactResponse,
    ContactUnsubscribeRequest,
    ContactUnsubscribeTokenResponse,
    ContactUpdateRequest,
    PublicUnsubscribeRequest,
)
from libs.core.contacts.service import ContactService

router = APIRouter(prefix="/contacts", tags=["contacts"])


def _client_ip(request: Request) -> str | None:
    return request.client.host if request.client else None


@router.post("", response_model=ContactResponse, status_code=status.HTTP_201_CREATED)
async def create_contact(
    payload: ContactCreateRequest,
    request: Request,
    actor: Annotated[CurrentActor, Depends(get_current_actor)],
    _: Annotated[User, Depends(require_admin)],
    service: Annotated[ContactService, Depends(get_contact_service_dep)],
) -> ContactResponse:
    contact = await service.create_contact(
        actor=actor,
        payload=payload,
        ip_address=_client_ip(request),
        user_agent=request.headers.get("user-agent"),
    )
    return ContactResponse.from_model(contact)


@router.get("", response_model=ContactListResponse)
async def list_contacts(
    actor: Annotated[CurrentActor, Depends(get_current_actor)],
    _: Annotated[User, Depends(require_admin)],
    service: Annotated[ContactService, Depends(get_contact_service_dep)],
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
    lifecycle_status: ContactLifecycleStatus | None = None,
    search: Annotated[str | None, Query(max_length=320)] = None,
    email_domain: Annotated[str | None, Query(max_length=255)] = None,
) -> ContactListResponse:
    result = await service.list_contacts(
        actor=actor,
        query=ContactQueryParams(
            limit=limit,
            offset=offset,
            lifecycle_status=lifecycle_status,
            search=search,
            email_domain=email_domain,
        ),
    )
    return ContactListResponse(
        items=[ContactResponse.from_model(item) for item in result.items],
        total=result.total,
        limit=result.limit,
        offset=result.offset,
    )


@router.get("/{contact_id}", response_model=ContactResponse)
async def get_contact(
    contact_id: str,
    actor: Annotated[CurrentActor, Depends(get_current_actor)],
    _: Annotated[User, Depends(require_admin)],
    service: Annotated[ContactService, Depends(get_contact_service_dep)],
) -> ContactResponse:
    contact = await service.get_contact(actor=actor, contact_id=contact_id)
    return ContactResponse.from_model(contact)


@router.patch("/{contact_id}", response_model=ContactResponse)
async def update_contact(
    contact_id: str,
    payload: ContactUpdateRequest,
    request: Request,
    actor: Annotated[CurrentActor, Depends(get_current_actor)],
    _: Annotated[User, Depends(require_admin)],
    service: Annotated[ContactService, Depends(get_contact_service_dep)],
) -> ContactResponse:
    contact = await service.update_contact(
        actor=actor,
        contact_id=contact_id,
        payload=payload,
        ip_address=_client_ip(request),
        user_agent=request.headers.get("user-agent"),
    )
    return ContactResponse.from_model(contact)


@router.delete("/{contact_id}", response_model=MessageResponse)
async def delete_contact(
    contact_id: str,
    payload: ContactDeleteRequest,
    request: Request,
    actor: Annotated[CurrentActor, Depends(get_current_actor)],
    _: Annotated[User, Depends(require_admin)],
    service: Annotated[ContactService, Depends(get_contact_service_dep)],
) -> MessageResponse:
    await service.delete_contact(
        actor=actor,
        contact_id=contact_id,
        reason=payload.reason,
        ip_address=_client_ip(request),
        user_agent=request.headers.get("user-agent"),
    )
    return MessageResponse(message="Contact hard-deleted")


@router.post("/{contact_id}/unsubscribe", response_model=ContactResponse)
async def unsubscribe_contact(
    contact_id: str,
    payload: ContactUnsubscribeRequest,
    request: Request,
    actor: Annotated[CurrentActor, Depends(get_current_actor)],
    _: Annotated[User, Depends(require_admin)],
    service: Annotated[ContactService, Depends(get_contact_service_dep)],
) -> ContactResponse:
    contact = await service.unsubscribe_contact(
        actor=actor,
        contact_id=contact_id,
        reason=payload.reason,
        ip_address=_client_ip(request),
        user_agent=request.headers.get("user-agent"),
    )
    return ContactResponse.from_model(contact)


@router.post("/{contact_id}/unsubscribe-token", response_model=ContactUnsubscribeTokenResponse)
async def create_unsubscribe_token(
    contact_id: str,
    actor: Annotated[CurrentActor, Depends(get_current_actor)],
    _: Annotated[User, Depends(require_admin)],
    settings: Annotated[Settings, Depends(get_settings_dep)],
    service: Annotated[ContactService, Depends(get_contact_service_dep)],
) -> ContactUnsubscribeTokenResponse:
    token = await service.create_unsubscribe_token(actor=actor, contact_id=contact_id)
    unsubscribe_url = f"{settings.public_unsubscribe_base_url.rstrip('/')}/unsubscribe?t={token}"
    return ContactUnsubscribeTokenResponse(token=token, unsubscribe_url=unsubscribe_url)


@router.post("/unsubscribe/public", response_model=MessageResponse)
async def unsubscribe_public(
    payload: PublicUnsubscribeRequest,
    request: Request,
    service: Annotated[ContactService, Depends(get_contact_service_dep)],
) -> MessageResponse:
    await service.unsubscribe_public(
        token=payload.token,
        ip_address=_client_ip(request),
        user_agent=request.headers.get("user-agent"),
    )
    return MessageResponse(message="Contact unsubscribed")


@router.get("/{contact_id}/preferences", response_model=ContactPreferenceResponse)
async def get_contact_preferences(
    contact_id: str,
    actor: Annotated[CurrentActor, Depends(get_current_actor)],
    _: Annotated[User, Depends(require_admin)],
    service: Annotated[ContactService, Depends(get_contact_service_dep)],
) -> ContactPreferenceResponse:
    preferences = await service.get_preferences(actor=actor, contact_id=contact_id)
    return ContactPreferenceResponse.from_model(preferences)


@router.put("/{contact_id}/preferences", response_model=ContactPreferenceResponse)
async def set_contact_preferences(
    contact_id: str,
    payload: ContactPreferenceUpdateRequest,
    request: Request,
    actor: Annotated[CurrentActor, Depends(get_current_actor)],
    _: Annotated[User, Depends(require_admin)],
    service: Annotated[ContactService, Depends(get_contact_service_dep)],
) -> ContactPreferenceResponse:
    preferences = await service.set_preferences(
        actor=actor,
        contact_id=contact_id,
        payload=payload,
        ip_address=_client_ip(request),
        user_agent=request.headers.get("user-agent"),
    )
    return ContactPreferenceResponse.from_model(preferences)
