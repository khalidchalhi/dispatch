from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from functools import lru_cache
from typing import Any

from sqlalchemy import and_, exists, func, or_, select
from sqlalchemy.engine import Dialect
from sqlalchemy.ext.asyncio import AsyncSession

from libs.core.auth.repository import AuthRepository
from libs.core.auth.schemas import CurrentActor
from libs.core.config import Settings, get_settings
from libs.core.contacts.models import Contact, Preference, SubscriptionStatus
from libs.core.db.session import get_session_factory
from libs.core.db.uow import UnitOfWork
from libs.core.errors import NotFoundError, PermissionDeniedError, ValidationError
from libs.core.segments.dsl import SegmentDslCompiler
from libs.core.segments.models import Segment, SegmentSnapshot
from libs.core.segments.repository import SegmentRepository
from libs.core.segments.schemas import SegmentCreateRequest, SegmentUpdateRequest
from libs.core.suppression.models import SuppressionEntry

_DELETED_DESCRIPTION_PREFIX = "__dispatch_deleted__"
_INELIGIBLE_LIFECYCLE_STATUSES = {"suppressed", "unsubscribed", "bounced", "deleted"}


@dataclass(slots=True)
class SegmentRecord:
    segment: Segment
    description: str | None


@dataclass(slots=True)
class SegmentPreviewResult:
    total_count: int
    sample: list[Contact]


@dataclass(slots=True)
class SegmentFreezeResult:
    segment_id: str
    campaign_run_id: str
    matched_count: int
    eligible_count: int
    snapshot_rows: int
    excluded_counts: dict[str, int]


class SegmentService:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._session_factory = get_session_factory()
        self._compiler = SegmentDslCompiler()

    async def create_segment(
        self,
        *,
        actor: CurrentActor,
        payload: SegmentCreateRequest,
        ip_address: str | None,
        user_agent: str | None,
    ) -> SegmentRecord:
        self._require_admin(actor)
        self._compiler.compile_predicate(dict(payload.dsl_json))

        async with UnitOfWork(self._session_factory) as uow:
            repo = SegmentRepository(uow.require_session())
            segment = await repo.create_segment(
                name=self._require_non_empty(payload.name, field_name="name"),
                description=self._clean_optional_text(payload.description),
                definition=dict(payload.dsl_json),
            )
            await AuthRepository(uow.require_session()).write_audit_log(
                actor_type=actor.actor_type,
                actor_id=actor.user.id,
                action="segment.create",
                resource_type="segment",
                resource_id=segment.id,
                after_state={"name": segment.name},
                ip_address=ip_address,
                user_agent=user_agent,
            )
            return SegmentRecord(
                segment=segment,
                description=segment.description,
            )

    async def list_segments(self, *, actor: CurrentActor) -> list[SegmentRecord]:
        self._require_admin(actor)
        async with self._session_factory() as session:
            repo = SegmentRepository(session)
            segments = await repo.list_segments()
            visible: list[SegmentRecord] = []
            for segment in segments:
                description, is_deleted = self._decode_deleted_description(segment.description)
                if is_deleted:
                    continue
                visible.append(SegmentRecord(segment=segment, description=description))
            return visible

    async def get_segment(self, *, actor: CurrentActor, segment_id: str) -> SegmentRecord:
        self._require_admin(actor)
        async with self._session_factory() as session:
            repo = SegmentRepository(session)
            segment = await repo.get_segment_by_id(segment_id)
            if segment is None:
                raise NotFoundError("Segment not found")
            description, is_deleted = self._decode_deleted_description(segment.description)
            if is_deleted:
                raise NotFoundError("Segment not found")
            return SegmentRecord(segment=segment, description=description)

    async def update_segment(
        self,
        *,
        actor: CurrentActor,
        segment_id: str,
        payload: SegmentUpdateRequest,
        ip_address: str | None,
        user_agent: str | None,
    ) -> SegmentRecord:
        self._require_admin(actor)
        values: dict[str, object] = {}
        field_set = payload.model_fields_set

        if "name" in field_set and payload.name is not None:
            values["name"] = self._require_non_empty(payload.name, field_name="name")
        if "description" in field_set:
            values["description"] = self._clean_optional_text(payload.description)
        if "dsl_json" in field_set and payload.dsl_json is not None:
            self._compiler.compile_predicate(dict(payload.dsl_json))
            values["definition"] = dict(payload.dsl_json)

        async with UnitOfWork(self._session_factory) as uow:
            repo = SegmentRepository(uow.require_session())
            segment = await repo.get_segment_by_id(segment_id)
            if segment is None:
                raise NotFoundError("Segment not found")
            _, is_deleted = self._decode_deleted_description(segment.description)
            if is_deleted:
                raise NotFoundError("Segment not found")

            if values:
                await repo.update_segment(segment_id=segment_id, values=values)

            refreshed = await repo.get_segment_by_id(segment_id)
            if refreshed is None:
                raise NotFoundError("Segment not found")
            description, refreshed_deleted = self._decode_deleted_description(refreshed.description)
            if refreshed_deleted:
                raise NotFoundError("Segment not found")

            await AuthRepository(uow.require_session()).write_audit_log(
                actor_type=actor.actor_type,
                actor_id=actor.user.id,
                action="segment.update",
                resource_type="segment",
                resource_id=refreshed.id,
                after_state={"changed_fields": sorted(values.keys())},
                ip_address=ip_address,
                user_agent=user_agent,
            )
            return SegmentRecord(segment=refreshed, description=description)

    async def delete_segment(
        self,
        *,
        actor: CurrentActor,
        segment_id: str,
        ip_address: str | None,
        user_agent: str | None,
    ) -> None:
        self._require_admin(actor)
        async with UnitOfWork(self._session_factory) as uow:
            repo = SegmentRepository(uow.require_session())
            segment = await repo.get_segment_by_id(segment_id)
            if segment is None:
                raise NotFoundError("Segment not found")
            description, is_deleted = self._decode_deleted_description(segment.description)
            if is_deleted:
                raise NotFoundError("Segment not found")

            deleted_description = self._encode_deleted_description(description)
            await repo.update_segment(
                segment_id=segment.id,
                values={"description": deleted_description},
            )
            await AuthRepository(uow.require_session()).write_audit_log(
                actor_type=actor.actor_type,
                actor_id=actor.user.id,
                action="segment.delete",
                resource_type="segment",
                resource_id=segment.id,
                after_state={"deleted": True},
                ip_address=ip_address,
                user_agent=user_agent,
            )

    async def duplicate_segment(
        self,
        *,
        actor: CurrentActor,
        segment_id: str,
        ip_address: str | None,
        user_agent: str | None,
    ) -> SegmentRecord:
        self._require_admin(actor)
        async with UnitOfWork(self._session_factory) as uow:
            repo = SegmentRepository(uow.require_session())
            segment = await repo.get_segment_by_id(segment_id)
            if segment is None:
                raise NotFoundError("Segment not found")
            description, is_deleted = self._decode_deleted_description(segment.description)
            if is_deleted:
                raise NotFoundError("Segment not found")

            duplicated = await repo.create_segment(
                name=f"{segment.name} (Copy)",
                description=description,
                definition=dict(segment.definition),
            )
            await AuthRepository(uow.require_session()).write_audit_log(
                actor_type=actor.actor_type,
                actor_id=actor.user.id,
                action="segment.duplicate",
                resource_type="segment",
                resource_id=duplicated.id,
                after_state={"source_segment_id": segment.id, "name": duplicated.name},
                ip_address=ip_address,
                user_agent=user_agent,
            )
            return SegmentRecord(segment=duplicated, description=description)

    async def preview_segment(
        self,
        *,
        actor: CurrentActor,
        segment_id: str,
        sample_limit: int = 50,
    ) -> SegmentPreviewResult:
        self._require_admin(actor)
        if sample_limit < 1 or sample_limit > 200:
            raise ValidationError("sample_limit must be between 1 and 200")

        async with UnitOfWork(self._session_factory) as uow:
            repo = SegmentRepository(uow.require_session())
            segment = await repo.get_segment_by_id(segment_id)
            if segment is None:
                raise NotFoundError("Segment not found")
            _, is_deleted = self._decode_deleted_description(segment.description)
            if is_deleted:
                raise NotFoundError("Segment not found")

            predicate = self._compiler.compile_predicate(dict(segment.definition))
            count = await self._count_contacts(
                session=uow.require_session(),
                predicate=predicate,
                eligible_only=True,
            )
            sample = await self._fetch_sample_contacts(
                session=uow.require_session(),
                predicate=predicate,
                sample_limit=sample_limit,
            )
            await repo.update_segment(
                segment_id=segment.id,
                values={"cached_size": count, "cached_at": datetime.now(UTC)},
            )
            return SegmentPreviewResult(total_count=count, sample=sample)

    async def freeze_segment(
        self,
        *,
        segment_id: str,
        campaign_run_id: str,
        chunk_size: int = 5000,
    ) -> SegmentFreezeResult:
        if chunk_size < 1 or chunk_size > 50000:
            raise ValidationError("chunk_size must be between 1 and 50000")

        async with UnitOfWork(self._session_factory) as uow:
            session = uow.require_session()
            repo = SegmentRepository(session)

            segment = await repo.get_segment_by_id(segment_id)
            if segment is None:
                raise NotFoundError("Segment not found")
            _, is_deleted = self._decode_deleted_description(segment.description)
            if is_deleted:
                raise NotFoundError("Segment not found")

            campaign_run = await repo.get_campaign_run_by_id(campaign_run_id)
            if campaign_run is None:
                raise NotFoundError("Campaign run not found")

            existing_rows = await repo.count_snapshots_for_run(campaign_run_id=campaign_run.id)
            if existing_rows > 0:
                return SegmentFreezeResult(
                    segment_id=segment.id,
                    campaign_run_id=campaign_run.id,
                    matched_count=existing_rows,
                    eligible_count=existing_rows,
                    snapshot_rows=existing_rows,
                    excluded_counts={
                        "excluded_total": 0,
                        "suppressed": 0,
                        "unsubscribed": 0,
                        "hard_bounced": 0,
                    },
                )

            predicate = self._compiler.compile_predicate(dict(segment.definition))
            matched_count = await self._count_contacts(
                session=session,
                predicate=predicate,
                eligible_only=False,
            )
            eligible_count = await self._count_contacts(
                session=session,
                predicate=predicate,
                eligible_only=True,
            )
            excluded_counts = await self._count_excluded_contacts(
                session=session,
                predicate=predicate,
            )

            inserted_rows = await self._insert_snapshot_rows(
                session=session,
                campaign_run_id=campaign_run.id,
                predicate=predicate,
                chunk_size=chunk_size,
            )
            await repo.update_campaign_run(
                campaign_run_id=campaign_run.id,
                eligible_count=inserted_rows,
            )
            await repo.update_segment(
                segment_id=segment.id,
                values={"cached_size": eligible_count, "cached_at": datetime.now(UTC)},
            )
            await AuthRepository(session).write_audit_log(
                actor_type="system",
                actor_id=None,
                action="segment.freeze",
                resource_type="campaign_run",
                resource_id=campaign_run.id,
                after_state={
                    "segment_id": segment.id,
                    "matched_count": matched_count,
                    "eligible_count": eligible_count,
                    "snapshot_rows": inserted_rows,
                    "excluded_counts": excluded_counts,
                },
                ip_address=None,
                user_agent="segment.freeze",
            )

            return SegmentFreezeResult(
                segment_id=segment.id,
                campaign_run_id=campaign_run.id,
                matched_count=matched_count,
                eligible_count=eligible_count,
                snapshot_rows=inserted_rows,
                excluded_counts=excluded_counts,
            )

    async def _count_contacts(
        self,
        *,
        session: AsyncSession,
        predicate: Any,
        eligible_only: bool,
    ) -> int:
        stmt = self._build_contact_query(
            select(Contact.id),
            predicate=predicate,
            eligible_only=eligible_only,
        )
        count_stmt = select(func.count()).select_from(stmt.distinct().subquery())
        result = await session.execute(count_stmt)
        return int(result.scalar_one())

    async def _fetch_sample_contacts(
        self,
        *,
        session: AsyncSession,
        predicate: Any,
        sample_limit: int,
    ) -> list[Contact]:
        stmt = self._build_contact_query(
            select(Contact),
            predicate=predicate,
            eligible_only=True,
        ).order_by(Contact.created_at.desc(), Contact.id.desc())
        stmt = stmt.limit(sample_limit)
        result = await session.execute(stmt)
        return list(result.scalars().unique().all())

    async def _count_excluded_contacts(
        self,
        *,
        session: AsyncSession,
        predicate: Any,
    ) -> dict[str, int]:
        matched = await self._count_contacts(
            session=session,
            predicate=predicate,
            eligible_only=False,
        )
        eligible = await self._count_contacts(
            session=session,
            predicate=predicate,
            eligible_only=True,
        )
        suppressed_stmt = self._build_contact_query(
            select(Contact.id),
            predicate=predicate,
            eligible_only=False,
        ).where(
            or_(
                Contact.lifecycle_status == "suppressed",
                self._suppression_exists_expression(),
            )
        )
        suppressed_count = await self._count_from_id_query(session=session, stmt=suppressed_stmt)

        unsubscribed_stmt = self._build_contact_query(
            select(Contact.id),
            predicate=predicate,
            eligible_only=False,
        ).where(
            or_(
                Contact.lifecycle_status == "unsubscribed",
                SubscriptionStatus.status == "unsubscribed",
            )
        )
        unsubscribed_count = await self._count_from_id_query(
            session=session,
            stmt=unsubscribed_stmt,
        )

        hard_bounced_stmt = self._build_contact_query(
            select(Contact.id),
            predicate=predicate,
            eligible_only=False,
        ).where(Contact.lifecycle_status == "bounced")
        hard_bounced_count = await self._count_from_id_query(
            session=session,
            stmt=hard_bounced_stmt,
        )

        excluded_total = max(matched - eligible, 0)
        return {
            "excluded_total": excluded_total,
            "suppressed": suppressed_count,
            "unsubscribed": unsubscribed_count,
            "hard_bounced": hard_bounced_count,
        }

    async def _count_from_id_query(self, *, session: AsyncSession, stmt: Any) -> int:
        count_stmt = select(func.count()).select_from(stmt.distinct().subquery())
        result = await session.execute(count_stmt)
        return int(result.scalar_one())

    async def _insert_snapshot_rows(
        self,
        *,
        session: AsyncSession,
        campaign_run_id: str,
        predicate: Any,
        chunk_size: int,
    ) -> int:
        inserted_total = 0
        last_seen_contact_id: str | None = None
        dialect = self._require_dialect(session)

        while True:
            stmt = self._build_contact_query(
                select(
                    Contact.id,
                    Contact.email,
                    Contact.email_domain,
                    Contact.first_name,
                    Contact.last_name,
                    Contact.lifecycle_status,
                ),
                predicate=predicate,
                eligible_only=True,
            )
            if last_seen_contact_id is not None:
                stmt = stmt.where(Contact.id > last_seen_contact_id)
            stmt = stmt.order_by(Contact.id.asc()).limit(chunk_size)
            if dialect.name != "sqlite":
                stmt = stmt.with_for_update(skip_locked=True)

            result = await session.execute(stmt)
            rows = result.all()
            if not rows:
                break

            snapshot_rows: list[SegmentSnapshot] = []
            for row in rows:
                frozen_attributes = {
                    "email": row.email,
                    "email_domain": row.email_domain,
                    "first_name": row.first_name,
                    "last_name": row.last_name,
                    "lifecycle_status": row.lifecycle_status,
                }
                snapshot_rows.append(
                    SegmentSnapshot(
                        campaign_run_id=campaign_run_id,
                        contact_id=row.id,
                        included=True,
                        exclusion_reason=None,
                        frozen_attributes=frozen_attributes,
                    )
                )
            session.add_all(snapshot_rows)
            await session.flush()
            inserted_total += len(snapshot_rows)
            last_seen_contact_id = rows[-1].id

        return inserted_total

    def _build_contact_query(
        self,
        stmt: Any,
        *,
        predicate: Any,
        eligible_only: bool,
    ) -> Any:
        query = stmt.select_from(Contact).outerjoin(
            Preference,
            Preference.contact_id == Contact.id,
        ).outerjoin(
            SubscriptionStatus,
            and_(
                SubscriptionStatus.contact_id == Contact.id,
                SubscriptionStatus.channel == "email",
            ),
        )
        query = query.where(predicate)
        query = query.where(Contact.deleted_at.is_(None))
        if eligible_only:
            query = query.where(Contact.lifecycle_status.notin_(_INELIGIBLE_LIFECYCLE_STATUSES))
            query = query.where(
                or_(
                    SubscriptionStatus.status.is_(None),
                    SubscriptionStatus.status != "unsubscribed",
                )
            )
            query = query.where(~self._suppression_exists_expression())
        return query

    def _suppression_exists_expression(self) -> Any:
        return exists(
            select(SuppressionEntry.id)
            .where(func.lower(SuppressionEntry.email) == func.lower(Contact.email))
            .where(
                or_(
                    SuppressionEntry.expires_at.is_(None),
                    SuppressionEntry.expires_at > datetime.now(UTC),
                )
            )
        )

    @staticmethod
    def _decode_deleted_description(value: str | None) -> tuple[str | None, bool]:
        if value is None:
            return None, False
        if value == _DELETED_DESCRIPTION_PREFIX:
            return None, True
        prefix = f"{_DELETED_DESCRIPTION_PREFIX}:"
        if value.startswith(prefix):
            restored = value[len(prefix) :].strip()
            return restored or None, True
        return value, False

    @staticmethod
    def _encode_deleted_description(value: str | None) -> str:
        if value is None or not value.strip():
            return _DELETED_DESCRIPTION_PREFIX
        return f"{_DELETED_DESCRIPTION_PREFIX}:{value.strip()}"

    @staticmethod
    def _clean_optional_text(value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        if not cleaned:
            return None
        if cleaned.startswith(_DELETED_DESCRIPTION_PREFIX):
            raise ValidationError("description uses a reserved prefix")
        return cleaned

    @staticmethod
    def _require_non_empty(value: str, *, field_name: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValidationError(f"{field_name} is required")
        return cleaned

    @staticmethod
    def _require_admin(actor: CurrentActor) -> None:
        if actor.user.role != "admin":
            raise PermissionDeniedError("Admin role required")

    @staticmethod
    def _require_dialect(session: AsyncSession) -> Dialect:
        if session.bind is None:
            raise RuntimeError("Session bind is not available")
        return session.bind.dialect


@lru_cache(maxsize=1)
def get_segment_service() -> SegmentService:
    return SegmentService(get_settings())


def reset_segment_service_cache() -> None:
    get_segment_service.cache_clear()
