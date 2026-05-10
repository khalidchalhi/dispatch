from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

from jinja2 import StrictUndefined
from jinja2.exceptions import SecurityError, TemplateError
from jinja2.sandbox import SandboxedEnvironment

from libs.core.auth.repository import AuthRepository
from libs.core.auth.schemas import CurrentActor
from libs.core.config import Settings, get_settings
from libs.core.db.session import get_session_factory
from libs.core.db.uow import UnitOfWork
from libs.core.errors import ConflictError, NotFoundError, PermissionDeniedError, ValidationError
from libs.core.templates.models import Template, TemplateVersion
from libs.core.templates.repository import TemplateRepository
from libs.core.templates.schemas import (
    TemplateCreateRequest,
    TemplatePreviewRequest,
    TemplateVersionCreateRequest,
)

_ARCHIVE_PREFIX = "__dispatch_archived__"
_MERGE_TAG_TOKEN_PATTERN = re.compile(r"\{\{\s*(.*?)\s*\}\}", re.DOTALL)
_MERGE_TAG_EXPRESSION_PATTERN = re.compile(r"contact(?:\.[A-Za-z][A-Za-z0-9_]*)+")
_AVAILABLE_MERGE_TAGS: list[tuple[str, str]] = [
    ("{{contact.first_name}}", "First name"),
    ("{{contact.last_name}}", "Last name"),
    ("{{contact.email}}", "Email"),
    ("{{contact.company}}", "Company"),
    ("{{contact.title}}", "Job title"),
    ("{{contact.unsubscribe_url}}", "Unsubscribe URL"),
]


class _LockedDownSandbox(SandboxedEnvironment):
    def is_safe_attribute(self, obj: object, attr: str, value: object) -> bool:  # noqa: ANN001
        if attr.startswith("_"):
            return False
        return super().is_safe_attribute(obj, attr, value)

    def is_safe_callable(self, obj: object) -> bool:  # noqa: ANN001
        return False


@dataclass(slots=True)
class TemplateRecord:
    template: Template
    versions: list[TemplateVersion]
    category: str | None
    is_archived: bool
    head_version_number: int | None


@dataclass(slots=True)
class TemplatePreviewResult:
    template_id: str
    version_number: int
    rendered_subject: str
    rendered_body_text: str
    rendered_body_html: str | None


@dataclass(slots=True)
class _ArchiveState:
    category: str | None
    is_archived: bool


class TemplateService:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._session_factory = get_session_factory()
        self._renderer = _LockedDownSandbox(autoescape=False, undefined=StrictUndefined)
        self._renderer.globals.clear()
        self._renderer.filters.clear()
        self._renderer.tests.clear()

    async def create_template(
        self,
        *,
        actor: CurrentActor,
        payload: TemplateCreateRequest,
        ip_address: str | None,
        user_agent: str | None,
    ) -> TemplateRecord:
        self._require_admin(actor)
        name = self._require_non_empty_text(payload.name, field_name="name")
        description = self._clean_optional_text(payload.description)
        category = self._normalize_category(payload.category)
        subject = self._normalize_subject(payload.subject)
        body_text = self._require_non_empty_text(payload.body_text, field_name="body_text")
        body_html = self._clean_optional_text(payload.body_html)
        merge_tags = self._extract_merge_tags(
            subject=subject,
            body_text=body_text,
            body_html=body_html,
        )

        async with UnitOfWork(self._session_factory) as uow:
            repo = TemplateRepository(uow.require_session())
            template = await repo.create_template(
                name=name,
                description=description,
                category=category,
            )
            created_version = await repo.create_template_version(
                template_id=template.id,
                version_number=1,
                subject=subject,
                body_text=body_text,
                body_html=body_html,
                spintax_enabled=payload.spintax_enabled,
                merge_tags=merge_tags,
                created_by=actor.user.id,
                is_published=True,
            )
            await AuthRepository(uow.require_session()).write_audit_log(
                actor_type=actor.actor_type,
                actor_id=actor.user.id,
                action="template.create",
                resource_type="template",
                resource_id=template.id,
                after_state={"name": template.name, "category": category},
                ip_address=ip_address,
                user_agent=user_agent,
            )
            await AuthRepository(uow.require_session()).write_audit_log(
                actor_type=actor.actor_type,
                actor_id=actor.user.id,
                action="template.version.create",
                resource_type="template_version",
                resource_id=created_version.id,
                after_state={
                    "template_id": template.id,
                    "version_number": created_version.version_number,
                    "merge_tags_count": len(merge_tags),
                },
                ip_address=ip_address,
                user_agent=user_agent,
            )
            return TemplateRecord(
                template=template,
                versions=[created_version],
                category=category,
                is_archived=False,
                head_version_number=created_version.version_number,
            )

    async def create_template_version(
        self,
        *,
        actor: CurrentActor,
        template_id: str,
        payload: TemplateVersionCreateRequest,
        ip_address: str | None,
        user_agent: str | None,
    ) -> TemplateRecord:
        self._require_admin(actor)
        subject = self._normalize_subject(payload.subject)
        body_text = self._require_non_empty_text(payload.body_text, field_name="body_text")
        body_html = self._clean_optional_text(payload.body_html)
        merge_tags = self._extract_merge_tags(
            subject=subject,
            body_text=body_text,
            body_html=body_html,
        )

        async with UnitOfWork(self._session_factory) as uow:
            repo = TemplateRepository(uow.require_session())
            template = await repo.get_template_by_id(template_id)
            if template is None:
                raise NotFoundError("Template not found")
            archive_state = self._decode_archive_state(template.category)
            if archive_state.is_archived:
                raise ConflictError("Cannot add versions to an archived template")

            version_number = await repo.get_max_version_number(template_id=template.id) + 1
            await repo.unpublish_all_versions(template_id=template.id)
            version = await repo.create_template_version(
                template_id=template.id,
                version_number=version_number,
                subject=subject,
                body_text=body_text,
                body_html=body_html,
                spintax_enabled=payload.spintax_enabled,
                merge_tags=merge_tags,
                created_by=actor.user.id,
                is_published=True,
            )
            await repo.update_template(
                template_id=template.id,
                values={"name": template.name},
            )
            versions = await repo.list_template_versions(template_id=template.id)
            await AuthRepository(uow.require_session()).write_audit_log(
                actor_type=actor.actor_type,
                actor_id=actor.user.id,
                action="template.version.create",
                resource_type="template_version",
                resource_id=version.id,
                after_state={
                    "template_id": template.id,
                    "version_number": version.version_number,
                    "merge_tags_count": len(merge_tags),
                },
                ip_address=ip_address,
                user_agent=user_agent,
            )
            return TemplateRecord(
                template=template,
                versions=versions,
                category=archive_state.category,
                is_archived=False,
                head_version_number=version.version_number,
            )

    async def list_templates(self, *, actor: CurrentActor) -> list[TemplateRecord]:
        self._require_admin(actor)
        async with self._session_factory() as session:
            repo = TemplateRepository(session)
            templates = await repo.list_templates()
            records: list[TemplateRecord] = []
            for template in templates:
                archive_state = self._decode_archive_state(template.category)
                head = await repo.get_head_template_version(template_id=template.id)
                head_version_number: int | None
                if head is not None:
                    head_version_number = head.version_number
                else:
                    max_version = await repo.get_max_version_number(template_id=template.id)
                    head_version_number = max_version if max_version > 0 else None
                records.append(
                    TemplateRecord(
                        template=template,
                        versions=[],
                        category=archive_state.category,
                        is_archived=archive_state.is_archived,
                        head_version_number=head_version_number,
                    )
                )
            return records

    async def get_template(self, *, actor: CurrentActor, template_id: str) -> TemplateRecord:
        self._require_admin(actor)
        async with self._session_factory() as session:
            repo = TemplateRepository(session)
            template = await repo.get_template_by_id(template_id)
            if template is None:
                raise NotFoundError("Template not found")
            versions = await repo.list_template_versions(template_id=template.id)
            head = await repo.get_head_template_version(template_id=template.id)
            if head is not None:
                head_version_number = head.version_number
            elif versions:
                head_version_number = versions[-1].version_number
            else:
                head_version_number = None
            archive_state = self._decode_archive_state(template.category)
            return TemplateRecord(
                template=template,
                versions=versions,
                category=archive_state.category,
                is_archived=archive_state.is_archived,
                head_version_number=head_version_number,
            )

    async def get_template_version(
        self,
        *,
        actor: CurrentActor,
        template_id: str,
        version_number: int,
    ) -> TemplateVersion:
        self._require_admin(actor)
        async with self._session_factory() as session:
            repo = TemplateRepository(session)
            template = await repo.get_template_by_id(template_id)
            if template is None:
                raise NotFoundError("Template not found")
            version = await repo.get_template_version_by_number(
                template_id=template_id,
                version_number=version_number,
            )
            if version is None:
                raise NotFoundError("Template version not found")
            return version

    async def archive_template(
        self,
        *,
        actor: CurrentActor,
        template_id: str,
        ip_address: str | None,
        user_agent: str | None,
    ) -> TemplateRecord:
        self._require_admin(actor)
        async with UnitOfWork(self._session_factory) as uow:
            repo = TemplateRepository(uow.require_session())
            template = await repo.get_template_by_id(template_id)
            if template is None:
                raise NotFoundError("Template not found")
            archive_state = self._decode_archive_state(template.category)
            if not archive_state.is_archived:
                archived_category = self._encode_archived_category(archive_state.category)
                await repo.update_template(
                    template_id=template.id,
                    values={"category": archived_category},
                )
            refreshed = await repo.get_template_by_id(template.id)
            if refreshed is None:
                raise NotFoundError("Template not found")
            versions = await repo.list_template_versions(template_id=template.id)
            head = await repo.get_head_template_version(template_id=template.id)
            if head is not None:
                head_version_number = head.version_number
            elif versions:
                head_version_number = versions[-1].version_number
            else:
                head_version_number = None
            refreshed_archive_state = self._decode_archive_state(refreshed.category)
            await AuthRepository(uow.require_session()).write_audit_log(
                actor_type=actor.actor_type,
                actor_id=actor.user.id,
                action="template.archive",
                resource_type="template",
                resource_id=template.id,
                after_state={"is_archived": True},
                ip_address=ip_address,
                user_agent=user_agent,
            )
            return TemplateRecord(
                template=refreshed,
                versions=versions,
                category=refreshed_archive_state.category,
                is_archived=True,
                head_version_number=head_version_number,
            )

    async def preview_template(
        self,
        *,
        actor: CurrentActor,
        template_id: str,
        payload: TemplatePreviewRequest,
    ) -> TemplatePreviewResult:
        self._require_admin(actor)
        sample_contact = dict(payload.sample_contact)
        async with self._session_factory() as session:
            repo = TemplateRepository(session)
            template = await repo.get_template_by_id(template_id)
            if template is None:
                raise NotFoundError("Template not found")

            version: TemplateVersion | None
            if payload.version_number is not None:
                version = await repo.get_template_version_by_number(
                    template_id=template_id,
                    version_number=payload.version_number,
                )
            else:
                version = await repo.get_head_template_version(template_id=template_id)
                if version is None:
                    max_version = await repo.get_max_version_number(template_id=template_id)
                    if max_version > 0:
                        version = await repo.get_template_version_by_number(
                            template_id=template_id,
                            version_number=max_version,
                        )
            if version is None:
                raise NotFoundError("Template version not found")

            rendered_subject = self._render_string(
                version.subject,
                sample_contact=sample_contact,
            )
            rendered_body_text = self._render_string(
                version.body_text,
                sample_contact=sample_contact,
            )
            rendered_body_html = (
                self._render_string(version.body_html, sample_contact=sample_contact)
                if version.body_html is not None
                else None
            )
            return TemplatePreviewResult(
                template_id=template_id,
                version_number=version.version_number,
                rendered_subject=rendered_subject,
                rendered_body_text=rendered_body_text,
                rendered_body_html=rendered_body_html,
            )

    async def assert_version_is_immutable(
        self,
        *,
        actor: CurrentActor,
        template_id: str,
        version_number: int,
    ) -> None:
        self._require_admin(actor)
        _ = await self.get_template_version(
            actor=actor,
            template_id=template_id,
            version_number=version_number,
        )
        raise ConflictError("Template versions are immutable")

    async def publish_template_version(
        self,
        *,
        actor: CurrentActor,
        template_id: str,
        version_number: int,
        ip_address: str | None,
        user_agent: str | None,
    ) -> TemplateRecord:
        self._require_admin(actor)
        async with UnitOfWork(self._session_factory) as uow:
            repo = TemplateRepository(uow.require_session())
            template = await repo.get_template_by_id(template_id)
            if template is None:
                raise NotFoundError("Template not found")

            archive_state = self._decode_archive_state(template.category)
            if archive_state.is_archived:
                raise ConflictError("Cannot publish a version for an archived template")

            version = await repo.get_template_version_by_number(
                template_id=template_id,
                version_number=version_number,
            )
            if version is None:
                raise NotFoundError("Template version not found")

            await repo.unpublish_all_versions(template_id=template_id)
            await repo.publish_version(
                template_id=template_id,
                version_number=version_number,
            )
            versions = await repo.list_template_versions(template_id=template_id)
            await AuthRepository(uow.require_session()).write_audit_log(
                actor_type=actor.actor_type,
                actor_id=actor.user.id,
                action="template.version.publish",
                resource_type="template_version",
                resource_id=version.id,
                after_state={
                    "template_id": template_id,
                    "version_number": version_number,
                    "published": True,
                },
                ip_address=ip_address,
                user_agent=user_agent,
            )
            return TemplateRecord(
                template=template,
                versions=versions,
                category=archive_state.category,
                is_archived=False,
                head_version_number=version_number,
            )

    async def list_available_merge_tags(
        self,
        *,
        actor: CurrentActor,
    ) -> list[dict[str, str]]:
        self._require_admin(actor)
        return [{"tag": tag, "label": label} for tag, label in _AVAILABLE_MERGE_TAGS]

    def _render_string(self, value: str, *, sample_contact: dict[str, Any]) -> str:
        self._validate_template_string(value)
        try:
            compiled = self._renderer.from_string(value)
            rendered = compiled.render(contact=sample_contact)
        except (SecurityError, TemplateError) as exc:
            raise ValidationError("Template rendering failed") from exc
        if not isinstance(rendered, str):
            raise ValidationError("Template rendering failed")
        return rendered

    def _extract_merge_tags(
        self,
        *,
        subject: str,
        body_text: str,
        body_html: str | None,
    ) -> list[str]:
        tags: set[str] = set()
        for value in (subject, body_text, body_html):
            if value is None:
                continue
            tags.update(self._extract_merge_tags_from_string(value))
        return sorted(tags)

    def _extract_merge_tags_from_string(self, value: str) -> set[str]:
        self._validate_template_string(value)
        tags: set[str] = set()
        for match in _MERGE_TAG_TOKEN_PATTERN.finditer(value):
            expression = match.group(1).strip()
            tags.add(expression)
        return tags

    def _validate_template_string(self, value: str) -> None:
        if "{%" in value or "%}" in value or "{#" in value or "#}" in value:
            raise ValidationError("Only merge tags are allowed in templates")
        for match in _MERGE_TAG_TOKEN_PATTERN.finditer(value):
            expression = match.group(1).strip()
            if not _MERGE_TAG_EXPRESSION_PATTERN.fullmatch(expression):
                raise ValidationError(
                    "Invalid merge tag expression. Only contact.field paths are allowed"
                )
        remainder = _MERGE_TAG_TOKEN_PATTERN.sub("", value)
        if "{{" in remainder or "}}" in remainder:
            raise ValidationError("Malformed merge tag syntax")

    @staticmethod
    def _require_non_empty_text(value: str, *, field_name: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValidationError(f"{field_name} is required")
        return cleaned

    @staticmethod
    def _normalize_subject(value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValidationError("subject is required")
        if "\r" in cleaned or "\n" in cleaned:
            raise ValidationError("subject must not contain CRLF characters")
        return cleaned

    @staticmethod
    def _clean_optional_text(value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        return cleaned if cleaned else None

    def _normalize_category(self, value: str | None) -> str | None:
        cleaned = self._clean_optional_text(value)
        if cleaned is None:
            return None
        if cleaned.startswith(_ARCHIVE_PREFIX):
            raise ValidationError("category uses a reserved prefix")
        return cleaned

    @staticmethod
    def _decode_archive_state(value: str | None) -> _ArchiveState:
        if value is None:
            return _ArchiveState(category=None, is_archived=False)
        if value == _ARCHIVE_PREFIX:
            return _ArchiveState(category=None, is_archived=True)
        prefix = f"{_ARCHIVE_PREFIX}:"
        if value.startswith(prefix):
            restored = value[len(prefix) :].strip()
            return _ArchiveState(category=restored or None, is_archived=True)
        return _ArchiveState(category=value, is_archived=False)

    @staticmethod
    def _encode_archived_category(value: str | None) -> str:
        cleaned = value.strip() if value is not None else ""
        if not cleaned:
            return _ARCHIVE_PREFIX
        return f"{_ARCHIVE_PREFIX}:{cleaned}"

    @staticmethod
    def _require_admin(actor: CurrentActor) -> None:
        if actor.user.role != "admin":
            raise PermissionDeniedError("Admin role required")


@lru_cache(maxsize=1)
def get_template_service() -> TemplateService:
    return TemplateService(get_settings())


def reset_template_service_cache() -> None:
    get_template_service.cache_clear()
