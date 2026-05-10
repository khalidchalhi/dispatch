from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import desc, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from libs.core.templates.models import Template, TemplateVersion


class TemplateRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create_template(
        self,
        *,
        name: str,
        description: str | None,
        category: str | None,
    ) -> Template:
        template = Template(
            name=name,
            description=description,
            category=category,
            updated_at=datetime.now(UTC),
        )
        self.session.add(template)
        await self.session.flush()
        return template

    async def get_template_by_id(self, template_id: str) -> Template | None:
        stmt = select(Template).where(Template.id == template_id)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_templates(self) -> list[Template]:
        stmt = select(Template).order_by(desc(Template.updated_at), desc(Template.id))
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def update_template(
        self,
        *,
        template_id: str,
        values: dict[str, object],
    ) -> bool:
        if not values:
            return False
        values_with_timestamp = dict(values)
        values_with_timestamp["updated_at"] = datetime.now(UTC)
        stmt = (
            update(Template)
            .where(Template.id == template_id)
            .values(**values_with_timestamp)
            .execution_options(synchronize_session="fetch")
        )
        result = await self.session.execute(stmt)
        return bool(getattr(result, "rowcount", 0))

    async def create_template_version(
        self,
        *,
        template_id: str,
        version_number: int,
        subject: str,
        body_text: str,
        body_html: str | None,
        spintax_enabled: bool,
        merge_tags: list[str],
        created_by: str,
        is_published: bool,
    ) -> TemplateVersion:
        version = TemplateVersion(
            template_id=template_id,
            version_number=version_number,
            subject=subject,
            body_text=body_text,
            body_html=body_html,
            spintax_enabled=spintax_enabled,
            merge_tags=merge_tags,
            created_by=created_by,
            is_published=is_published,
        )
        self.session.add(version)
        await self.session.flush()
        return version

    async def list_template_versions(self, *, template_id: str) -> list[TemplateVersion]:
        stmt = (
            select(TemplateVersion)
            .where(TemplateVersion.template_id == template_id)
            .order_by(TemplateVersion.version_number.asc())
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_template_version_by_number(
        self,
        *,
        template_id: str,
        version_number: int,
    ) -> TemplateVersion | None:
        stmt = (
            select(TemplateVersion)
            .where(TemplateVersion.template_id == template_id)
            .where(TemplateVersion.version_number == version_number)
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_head_template_version(self, *, template_id: str) -> TemplateVersion | None:
        stmt = (
            select(TemplateVersion)
            .where(TemplateVersion.template_id == template_id)
            .where(TemplateVersion.is_published.is_(True))
            .order_by(TemplateVersion.version_number.desc())
            .limit(1)
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_max_version_number(self, *, template_id: str) -> int:
        stmt = select(func.max(TemplateVersion.version_number)).where(
            TemplateVersion.template_id == template_id
        )
        result = await self.session.execute(stmt)
        max_version = result.scalar_one_or_none()
        if max_version is None:
            return 0
        return int(max_version)

    async def unpublish_all_versions(self, *, template_id: str) -> int:
        stmt = (
            update(TemplateVersion)
            .where(TemplateVersion.template_id == template_id)
            .where(TemplateVersion.is_published.is_(True))
            .values(is_published=False)
            .execution_options(synchronize_session="fetch")
        )
        result = await self.session.execute(stmt)
        return int(getattr(result, "rowcount", 0) or 0)

    async def publish_version(self, *, template_id: str, version_number: int) -> bool:
        stmt = (
            update(TemplateVersion)
            .where(TemplateVersion.template_id == template_id)
            .where(TemplateVersion.version_number == version_number)
            .values(is_published=True)
            .execution_options(synchronize_session="fetch")
        )
        result = await self.session.execute(stmt)
        return bool(getattr(result, "rowcount", 0))
