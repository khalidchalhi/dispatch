from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Request, status

from apps.api.deps import get_current_actor, get_template_service_dep, require_admin
from libs.core.auth.models import User
from libs.core.auth.schemas import CurrentActor, MessageResponse
from libs.core.templates.schemas import (
    TemplateCreateRequest,
    TemplateListResponse,
    TemplateMergeTagResponse,
    TemplatePreviewRequest,
    TemplatePreviewResponse,
    TemplateResponse,
    TemplateVersionCreateRequest,
    TemplateVersionResponse,
)
from libs.core.templates.service import TemplateService

router = APIRouter(prefix="/templates", tags=["templates"])


def _client_ip(request: Request) -> str | None:
    return request.client.host if request.client else None


@router.get("/merge-tags", response_model=list[TemplateMergeTagResponse])
async def list_merge_tags(
    actor: Annotated[CurrentActor, Depends(get_current_actor)],
    _: Annotated[User, Depends(require_admin)],
    service: Annotated[TemplateService, Depends(get_template_service_dep)],
) -> list[TemplateMergeTagResponse]:
    merge_tags = await service.list_available_merge_tags(actor=actor)
    return [TemplateMergeTagResponse(tag=item["tag"], label=item["label"]) for item in merge_tags]


@router.post("", response_model=TemplateResponse, status_code=status.HTTP_201_CREATED)
async def create_template(
    payload: TemplateCreateRequest,
    request: Request,
    actor: Annotated[CurrentActor, Depends(get_current_actor)],
    _: Annotated[User, Depends(require_admin)],
    service: Annotated[TemplateService, Depends(get_template_service_dep)],
) -> TemplateResponse:
    created = await service.create_template(
        actor=actor,
        payload=payload,
        ip_address=_client_ip(request),
        user_agent=request.headers.get("user-agent"),
    )
    return TemplateResponse.from_model(
        created.template,
        category=created.category,
        is_archived=created.is_archived,
        head_version_number=created.head_version_number,
        versions=created.versions,
    )


@router.post("/{template_id}/versions", response_model=TemplateResponse)
async def create_template_version(
    template_id: str,
    payload: TemplateVersionCreateRequest,
    request: Request,
    actor: Annotated[CurrentActor, Depends(get_current_actor)],
    _: Annotated[User, Depends(require_admin)],
    service: Annotated[TemplateService, Depends(get_template_service_dep)],
) -> TemplateResponse:
    updated = await service.create_template_version(
        actor=actor,
        template_id=template_id,
        payload=payload,
        ip_address=_client_ip(request),
        user_agent=request.headers.get("user-agent"),
    )
    return TemplateResponse.from_model(
        updated.template,
        category=updated.category,
        is_archived=updated.is_archived,
        head_version_number=updated.head_version_number,
        versions=updated.versions,
    )


@router.get("", response_model=TemplateListResponse)
async def list_templates(
    actor: Annotated[CurrentActor, Depends(get_current_actor)],
    _: Annotated[User, Depends(require_admin)],
    service: Annotated[TemplateService, Depends(get_template_service_dep)],
) -> TemplateListResponse:
    records = await service.list_templates(actor=actor)
    return TemplateListResponse(
        items=[
            TemplateResponse.from_model(
                item.template,
                category=item.category,
                is_archived=item.is_archived,
                head_version_number=item.head_version_number,
                versions=[],
            )
            for item in records
        ]
    )


@router.get("/{template_id}", response_model=TemplateResponse)
async def get_template(
    template_id: str,
    actor: Annotated[CurrentActor, Depends(get_current_actor)],
    _: Annotated[User, Depends(require_admin)],
    service: Annotated[TemplateService, Depends(get_template_service_dep)],
) -> TemplateResponse:
    record = await service.get_template(actor=actor, template_id=template_id)
    return TemplateResponse.from_model(
        record.template,
        category=record.category,
        is_archived=record.is_archived,
        head_version_number=record.head_version_number,
        versions=record.versions,
    )


@router.get("/{template_id}/versions/{version_number}", response_model=TemplateVersionResponse)
async def get_template_version(
    template_id: str,
    version_number: int,
    actor: Annotated[CurrentActor, Depends(get_current_actor)],
    _: Annotated[User, Depends(require_admin)],
    service: Annotated[TemplateService, Depends(get_template_service_dep)],
) -> TemplateVersionResponse:
    version = await service.get_template_version(
        actor=actor,
        template_id=template_id,
        version_number=version_number,
    )
    return TemplateVersionResponse.from_model(version)


@router.post("/{template_id}/versions/{version_number}/publish", response_model=TemplateResponse)
async def publish_template_version(
    template_id: str,
    version_number: int,
    request: Request,
    actor: Annotated[CurrentActor, Depends(get_current_actor)],
    _: Annotated[User, Depends(require_admin)],
    service: Annotated[TemplateService, Depends(get_template_service_dep)],
) -> TemplateResponse:
    published = await service.publish_template_version(
        actor=actor,
        template_id=template_id,
        version_number=version_number,
        ip_address=_client_ip(request),
        user_agent=request.headers.get("user-agent"),
    )
    return TemplateResponse.from_model(
        published.template,
        category=published.category,
        is_archived=published.is_archived,
        head_version_number=published.head_version_number,
        versions=published.versions,
    )


@router.patch("/{template_id}/versions/{version_number}", response_model=MessageResponse)
async def update_template_version(
    template_id: str,
    version_number: int,
    actor: Annotated[CurrentActor, Depends(get_current_actor)],
    _: Annotated[User, Depends(require_admin)],
    service: Annotated[TemplateService, Depends(get_template_service_dep)],
) -> MessageResponse:
    await service.assert_version_is_immutable(
        actor=actor,
        template_id=template_id,
        version_number=version_number,
    )
    return MessageResponse(message="Template version updated")


@router.post("/{template_id}/preview", response_model=TemplatePreviewResponse)
async def preview_template(
    template_id: str,
    payload: TemplatePreviewRequest,
    actor: Annotated[CurrentActor, Depends(get_current_actor)],
    _: Annotated[User, Depends(require_admin)],
    service: Annotated[TemplateService, Depends(get_template_service_dep)],
) -> TemplatePreviewResponse:
    preview = await service.preview_template(
        actor=actor,
        template_id=template_id,
        payload=payload,
    )
    return TemplatePreviewResponse(
        template_id=preview.template_id,
        version_number=preview.version_number,
        rendered_subject=preview.rendered_subject,
        rendered_body_text=preview.rendered_body_text,
        rendered_body_html=preview.rendered_body_html,
    )


@router.post("/{template_id}/archive", response_model=TemplateResponse)
async def archive_template(
    template_id: str,
    request: Request,
    actor: Annotated[CurrentActor, Depends(get_current_actor)],
    _: Annotated[User, Depends(require_admin)],
    service: Annotated[TemplateService, Depends(get_template_service_dep)],
) -> TemplateResponse:
    archived = await service.archive_template(
        actor=actor,
        template_id=template_id,
        ip_address=_client_ip(request),
        user_agent=request.headers.get("user-agent"),
    )
    return TemplateResponse.from_model(
        archived.template,
        category=archived.category,
        is_archived=archived.is_archived,
        head_version_number=archived.head_version_number,
        versions=archived.versions,
    )
