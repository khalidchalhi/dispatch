from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from libs.core.templates.models import Template, TemplateVersion


class TemplateVersionCreateRequest(BaseModel):
    subject: str = Field(min_length=1, max_length=998)
    body_text: str = Field(min_length=1)
    body_html: str | None = None
    spintax_enabled: bool = True


class TemplateCreateRequest(TemplateVersionCreateRequest):
    name: str = Field(min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=2000)
    category: str | None = Field(default=None, max_length=255)


class TemplatePreviewRequest(BaseModel):
    sample_contact: dict[str, Any] = Field(default_factory=dict)
    version_number: int | None = Field(default=None, ge=1)


class TemplateVersionResponse(BaseModel):
    id: str
    template_id: str
    version_number: int
    subject: str
    body_text: str
    body_html: str | None
    spintax_enabled: bool
    merge_tags: list[str]
    ml_spam_score: float | None
    is_published: bool
    created_by: str
    created_at: datetime

    @classmethod
    def from_model(cls, version: TemplateVersion) -> TemplateVersionResponse:
        return cls(
            id=version.id,
            template_id=version.template_id,
            version_number=version.version_number,
            subject=version.subject,
            body_text=version.body_text,
            body_html=version.body_html,
            spintax_enabled=version.spintax_enabled,
            merge_tags=list(version.merge_tags),
            ml_spam_score=float(version.ml_spam_score)
            if version.ml_spam_score is not None
            else None,
            is_published=version.is_published,
            created_by=version.created_by,
            created_at=version.created_at,
        )


class TemplateResponse(BaseModel):
    id: str
    name: str
    description: str | None
    category: str | None
    is_archived: bool
    head_version_number: int | None
    created_at: datetime
    updated_at: datetime
    versions: list[TemplateVersionResponse] = Field(default_factory=list)

    @classmethod
    def from_model(
        cls,
        template: Template,
        *,
        category: str | None,
        is_archived: bool,
        head_version_number: int | None,
        versions: list[TemplateVersion] | None = None,
    ) -> TemplateResponse:
        return cls(
            id=template.id,
            name=template.name,
            description=template.description,
            category=category,
            is_archived=is_archived,
            head_version_number=head_version_number,
            created_at=template.created_at,
            updated_at=template.updated_at,
            versions=[
                TemplateVersionResponse.from_model(item) for item in (versions or [])
            ],
        )


class TemplateListResponse(BaseModel):
    items: list[TemplateResponse]


class TemplatePreviewResponse(BaseModel):
    template_id: str
    version_number: int
    rendered_subject: str
    rendered_body_text: str
    rendered_body_html: str | None


class TemplateMergeTagResponse(BaseModel):
    tag: str
    label: str
