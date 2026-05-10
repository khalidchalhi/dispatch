from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from libs.core.analytics.service import AnalyticsService, get_analytics_service
from libs.core.auth.models import User
from libs.core.auth.schemas import CurrentActor
from libs.core.auth.service import AuthService, UserService, get_auth_service
from libs.core.campaigns.service import CampaignService, get_campaign_service
from libs.core.circuit_breaker.service import CircuitBreakerService, get_circuit_breaker_service
from libs.core.config import Settings, get_settings
from libs.core.contacts.service import ContactService, get_contact_service
from libs.core.db.session import get_session
from libs.core.domains.service import DomainService, get_domain_service
from libs.core.errors import PermissionDeniedError
from libs.core.imports.service import ImportService, get_import_service
from libs.core.lists.service import ListService, get_list_service
from libs.core.segments.service import SegmentService, get_segment_service
from libs.core.sender_profiles.service import SenderProfileService, get_sender_profile_service
from libs.core.suppression.service import SuppressionService, get_suppression_service
from libs.core.templates.service import TemplateService, get_template_service
from libs.core.warmup.service import WarmupService, get_warmup_service

bearer_scheme = HTTPBearer(auto_error=False)


def get_settings_dep() -> Settings:
    return get_settings()


async def get_db_session() -> AsyncIterator[AsyncSession]:
    async for session in get_session():
        yield session


def get_analytics_service_dep() -> AnalyticsService:
    return get_analytics_service()


def get_auth_service_dep() -> AuthService:
    return get_auth_service()


def get_user_service_dep(
    auth_service: Annotated[AuthService, Depends(get_auth_service_dep)],
) -> UserService:
    return UserService(auth_service)


def get_domain_service_dep() -> DomainService:
    return get_domain_service()


def get_sender_profile_service_dep() -> SenderProfileService:
    return get_sender_profile_service()


def get_contact_service_dep() -> ContactService:
    return get_contact_service()


def get_campaign_service_dep() -> CampaignService:
    return get_campaign_service()


def get_circuit_breaker_service_dep() -> CircuitBreakerService:
    return get_circuit_breaker_service()


def get_list_service_dep() -> ListService:
    return get_list_service()


def get_import_service_dep() -> ImportService:
    return get_import_service()


def get_template_service_dep() -> TemplateService:
    return get_template_service()


def get_segment_service_dep() -> SegmentService:
    return get_segment_service()


def get_suppression_service_dep() -> SuppressionService:
    return get_suppression_service()


def get_warmup_service_dep() -> WarmupService:
    return get_warmup_service()


async def get_current_actor(
    request: Request,
    settings: Annotated[Settings, Depends(get_settings_dep)],
    auth_service: Annotated[AuthService, Depends(get_auth_service_dep)],
    bearer: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
) -> CurrentActor:
    authorization = None
    if bearer is not None:
        authorization = f"{bearer.scheme} {bearer.credentials}"

    session_cookie = request.cookies.get(settings.session_cookie_name)
    return await auth_service.resolve_current_actor(
        authorization=authorization,
        session_cookie=session_cookie,
    )


async def get_current_user(
    actor: Annotated[CurrentActor, Depends(get_current_actor)],
) -> User:
    return actor.user


async def require_admin(
    user: Annotated[User, Depends(get_current_user)],
) -> User:
    if user.role != "admin":
        raise PermissionDeniedError("Admin role required")
    return user
