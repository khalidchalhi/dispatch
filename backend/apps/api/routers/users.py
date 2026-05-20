from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Request, status

from apps.api.deps import get_current_actor, get_user_service_dep, require_admin
from libs.core.auth.models import User
from libs.core.auth.schemas import (
    ApiKeyCreateRequest,
    ApiKeyCreateResponse,
    ApiKeyResponse,
    ApiKeyRotateRequest,
    AuthFlow,
    CurrentActor,
    MessageResponse,
    MFAEnrollResponse,
    MFAVerifyRequest,
    PasswordChangeRequest,
    UserCreateRequest,
    UserDisableRequest,
    UserListResponse,
    UserResponse,
)
from libs.core.auth.service import UserService
from libs.core.errors import ValidationError

router = APIRouter(prefix="/users", tags=["users"])


def _client_ip(request: Request) -> str | None:
    return request.client.host if request.client else None


@router.get("", response_model=UserListResponse)
async def list_users(
    actor: Annotated[CurrentActor, Depends(get_current_actor)],
    _: Annotated[User, Depends(require_admin)],
    user_service: Annotated[UserService, Depends(get_user_service_dep)],
) -> UserListResponse:
    users = await user_service.list_users(actor=actor)
    return UserListResponse(items=[UserResponse.from_model(user) for user in users])


@router.post("", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def create_user(
    payload: UserCreateRequest,
    request: Request,
    actor: Annotated[CurrentActor, Depends(get_current_actor)],
    _: Annotated[User, Depends(require_admin)],
    user_service: Annotated[UserService, Depends(get_user_service_dep)],
) -> UserResponse:
    user = await user_service.create_user(
        actor=actor,
        email=payload.email,
        password=payload.password,
        role=payload.role,
        ip_address=_client_ip(request),
        user_agent=request.headers.get("user-agent"),
    )
    return UserResponse.from_model(user)


@router.post("/{user_id}/disable", response_model=MessageResponse)
async def disable_user(
    user_id: str,
    request: Request,
    payload: UserDisableRequest,
    actor: Annotated[CurrentActor, Depends(get_current_actor)],
    _: Annotated[User, Depends(require_admin)],
    user_service: Annotated[UserService, Depends(get_user_service_dep)],
) -> MessageResponse:
    await user_service.disable_user(
        actor=actor,
        user_id=user_id,
        reason=payload.reason,
        ip_address=_client_ip(request),
        user_agent=request.headers.get("user-agent"),
    )
    return MessageResponse(message="User disabled")


@router.post("/{user_id}/reset-mfa", response_model=MessageResponse)
async def reset_user_mfa(
    user_id: str,
    request: Request,
    actor: Annotated[CurrentActor, Depends(get_current_actor)],
    _: Annotated[User, Depends(require_admin)],
    user_service: Annotated[UserService, Depends(get_user_service_dep)],
) -> MessageResponse:
    await user_service.reset_user_mfa(
        actor=actor,
        user_id=user_id,
        ip_address=_client_ip(request),
        user_agent=request.headers.get("user-agent"),
    )
    return MessageResponse(message="MFA reset")


@router.get("/me", response_model=UserResponse)
async def get_me(
    actor: Annotated[CurrentActor, Depends(get_current_actor)],
) -> UserResponse:
    return UserResponse.from_model(actor.user)


@router.get("/{user_id}", response_model=UserResponse)
async def get_user(
    user_id: str,
    actor: Annotated[CurrentActor, Depends(get_current_actor)],
    _: Annotated[User, Depends(require_admin)],
    user_service: Annotated[UserService, Depends(get_user_service_dep)],
) -> UserResponse:
    user = await user_service.get_user_by_id(actor=actor, user_id=user_id)
    return UserResponse.from_model(user)


@router.post("/me/password", response_model=MessageResponse)
async def change_my_password(
    payload: PasswordChangeRequest,
    request: Request,
    actor: Annotated[CurrentActor, Depends(get_current_actor)],
    user_service: Annotated[UserService, Depends(get_user_service_dep)],
) -> MessageResponse:
    await user_service.change_password(
        actor=actor,
        current_password=payload.current_password,
        new_password=payload.new_password,
        ip_address=_client_ip(request),
        user_agent=request.headers.get("user-agent"),
    )
    return MessageResponse(message="Password changed")


@router.post("/me/mfa/enroll", response_model=MFAEnrollResponse)
async def enroll_mfa(
    actor: Annotated[CurrentActor, Depends(get_current_actor)],
    user_service: Annotated[UserService, Depends(get_user_service_dep)],
) -> MFAEnrollResponse:
    token, uri = await user_service.enroll_mfa_start(actor=actor)
    return MFAEnrollResponse(enrollment_token=token, otp_auth_uri=uri)


@router.post("/me/mfa/verify", response_model=MessageResponse)
async def verify_mfa_enrollment(
    payload: MFAVerifyRequest,
    request: Request,
    actor: Annotated[CurrentActor, Depends(get_current_actor)],
    user_service: Annotated[UserService, Depends(get_user_service_dep)],
) -> MessageResponse:
    if payload.flow != AuthFlow.ENROLL:
        raise ValidationError("Use flow=enroll for MFA enrollment verification")

    await user_service.verify_mfa_enrollment(
        actor=actor,
        enrollment_token=payload.token,
        code=payload.code,
        ip_address=_client_ip(request),
        user_agent=request.headers.get("user-agent"),
    )
    return MessageResponse(message="MFA enabled")


@router.get("/me/api-keys", response_model=list[ApiKeyResponse])
async def list_my_api_keys(
    actor: Annotated[CurrentActor, Depends(get_current_actor)],
    user_service: Annotated[UserService, Depends(get_user_service_dep)],
) -> list[ApiKeyResponse]:
    api_keys = await user_service.list_api_keys(actor=actor)
    return [ApiKeyResponse.from_model(api_key) for api_key in api_keys]


@router.post(
    "/me/api-keys",
    response_model=ApiKeyCreateResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_my_api_key(
    payload: ApiKeyCreateRequest,
    request: Request,
    actor: Annotated[CurrentActor, Depends(get_current_actor)],
    user_service: Annotated[UserService, Depends(get_user_service_dep)],
) -> ApiKeyCreateResponse:
    created = await user_service.create_api_key(
        actor=actor,
        name=payload.name,
        expires_at=payload.expires_at,
        ip_address=_client_ip(request),
        user_agent=request.headers.get("user-agent"),
    )
    return ApiKeyCreateResponse(
        api_key=ApiKeyResponse.from_model(created.model),
        plaintext_key=created.plaintext_key,
    )


@router.post("/me/api-keys/{api_key_id}/rotate", response_model=ApiKeyCreateResponse)
async def rotate_my_api_key(
    api_key_id: str,
    payload: ApiKeyRotateRequest,
    request: Request,
    actor: Annotated[CurrentActor, Depends(get_current_actor)],
    user_service: Annotated[UserService, Depends(get_user_service_dep)],
) -> ApiKeyCreateResponse:
    created = await user_service.rotate_api_key(
        actor=actor,
        api_key_id=api_key_id,
        name=payload.name,
        expires_at=payload.expires_at,
        ip_address=_client_ip(request),
        user_agent=request.headers.get("user-agent"),
    )
    return ApiKeyCreateResponse(
        api_key=ApiKeyResponse.from_model(created.model),
        plaintext_key=created.plaintext_key,
    )


@router.delete("/me/api-keys/{api_key_id}", response_model=MessageResponse)
async def revoke_my_api_key(
    api_key_id: str,
    request: Request,
    actor: Annotated[CurrentActor, Depends(get_current_actor)],
    user_service: Annotated[UserService, Depends(get_user_service_dep)],
) -> MessageResponse:
    await user_service.revoke_api_key(
        actor=actor,
        api_key_id=api_key_id,
        ip_address=_client_ip(request),
        user_agent=request.headers.get("user-agent"),
    )
    return MessageResponse(message="API key revoked")
