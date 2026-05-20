from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response, status

from apps.api.deps import (
    get_auth_service_dep,
    get_current_actor,
    get_settings_dep,
    get_user_service_dep,
)
from libs.core.auth.schemas import (
    ApiKeyResponse,
    AuthFlow,
    CurrentActor,
    LoginRequest,
    LoginResponse,
    MessageResponse,
    MFAVerifyRequest,
)
from libs.core.auth.service import AuthService, UserService
from libs.core.config import Settings
from libs.core.errors import ValidationError

router = APIRouter(prefix="/auth", tags=["auth"])


def _client_ip(request: Request) -> str | None:
    return request.client.host if request.client else None


def _set_session_cookie(response: Response, settings: Settings, session_cookie: str) -> None:
    response.set_cookie(
        key=settings.session_cookie_name,
        value=session_cookie,
        httponly=True,
        secure=settings.session_cookie_secure,
        samesite="strict",
        max_age=settings.session_ttl_seconds,
        path="/",
    )


@router.post("/login", response_model=LoginResponse)
async def login(
    payload: LoginRequest,
    request: Request,
    response: Response,
    settings: Annotated[Settings, Depends(get_settings_dep)],
    auth_service: Annotated[AuthService, Depends(get_auth_service_dep)],
) -> LoginResponse:
    result = await auth_service.login(
        email=payload.email,
        password=payload.password,
        ip_address=_client_ip(request),
        user_agent=request.headers.get("user-agent"),
    )

    if result.session_cookie:
        _set_session_cookie(response, settings, result.session_cookie)

    return LoginResponse(
        authenticated=result.authenticated,
        requires_mfa=result.requires_mfa,
        mfa_token=result.mfa_token,
    )


@router.post("/mfa/verify", response_model=LoginResponse)
async def verify_mfa(
    payload: MFAVerifyRequest,
    request: Request,
    response: Response,
    settings: Annotated[Settings, Depends(get_settings_dep)],
    auth_service: Annotated[AuthService, Depends(get_auth_service_dep)],
) -> LoginResponse:
    if payload.flow != AuthFlow.LOGIN:
        raise ValidationError("Only login MFA verification is supported on this endpoint")

    result = await auth_service.verify_mfa_login(
        mfa_token=payload.token,
        code=payload.code,
        ip_address=_client_ip(request),
        user_agent=request.headers.get("user-agent"),
    )
    if not result.session_cookie:
        raise ValidationError("MFA verification failed to create session")

    _set_session_cookie(response, settings, result.session_cookie)
    return LoginResponse(authenticated=True, requires_mfa=False)


@router.post("/logout", response_model=MessageResponse, status_code=status.HTTP_200_OK)
async def logout(
    request: Request,
    response: Response,
    settings: Annotated[Settings, Depends(get_settings_dep)],
    auth_service: Annotated[AuthService, Depends(get_auth_service_dep)],
) -> MessageResponse:
    await auth_service.logout(session_cookie=request.cookies.get(settings.session_cookie_name))
    response.delete_cookie(settings.session_cookie_name, path="/")
    return MessageResponse(message="Logged out")


@router.get("/api-keys", response_model=list[ApiKeyResponse])
async def list_api_keys(
    actor: Annotated[CurrentActor, Depends(get_current_actor)],
    user_service: Annotated[UserService, Depends(get_user_service_dep)],
) -> list[ApiKeyResponse]:
    api_keys = await user_service.list_api_keys(actor=actor)
    return [ApiKeyResponse.from_model(api_key) for api_key in api_keys]
