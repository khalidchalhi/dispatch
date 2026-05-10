from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from libs.core.imports.models import ImportJob, ImportRow

_ACTIVE_IMPORT_STATUSES = ("queued", "parsing", "validating", "upserting")


class ImportRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def count_active_jobs_for_user(self, user_id: str) -> int:
        stmt = (
            select(func.count())
            .select_from(ImportJob)
            .where(ImportJob.created_by == user_id)
            .where(ImportJob.status.in_(_ACTIVE_IMPORT_STATUSES))
        )
        result = await self.session.execute(stmt)
        return int(result.scalar_one())

    async def create_import_job(
        self,
        *,
        created_by: str,
        file_name: str,
        file_s3_key: str,
        file_size_bytes: int,
        column_mapping: dict[str, object],
        source_label: str | None,
        target_list_id: str | None,
    ) -> ImportJob:
        job = ImportJob(
            created_by=created_by,
            file_name=file_name,
            file_s3_key=file_s3_key,
            file_size_bytes=file_size_bytes,
            column_mapping=column_mapping,
            source_label=source_label,
            target_list_id=target_list_id,
            status="queued",
        )
        self.session.add(job)
        await self.session.flush()
        return job

    async def get_import_job_by_id(self, job_id: str) -> ImportJob | None:
        stmt = select(ImportJob).where(ImportJob.id == job_id)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def update_import_job(
        self,
        *,
        job_id: str,
        status: str | None = None,
        total_rows: int | None = None,
        valid_rows: int | None = None,
        invalid_rows: int | None = None,
        duplicate_rows: int | None = None,
        suppressed_rows: int | None = None,
        error_message: str | None = None,
        started_at: datetime | None = None,
        completed_at: datetime | None = None,
    ) -> bool:
        values: dict[str, object] = {}
        if status is not None:
            values["status"] = status
        if total_rows is not None:
            values["total_rows"] = total_rows
        if valid_rows is not None:
            values["valid_rows"] = valid_rows
        if invalid_rows is not None:
            values["invalid_rows"] = invalid_rows
        if duplicate_rows is not None:
            values["duplicate_rows"] = duplicate_rows
        if suppressed_rows is not None:
            values["suppressed_rows"] = suppressed_rows
        if error_message is not None:
            values["error_message"] = error_message
        if started_at is not None:
            values["started_at"] = started_at
        if completed_at is not None:
            values["completed_at"] = completed_at
        if not values:
            return False

        stmt = (
            update(ImportJob)
            .where(ImportJob.id == job_id)
            .values(**values)
            .execution_options(synchronize_session="fetch")
        )
        result = await self.session.execute(stmt)
        return bool(getattr(result, "rowcount", 0))

    async def mark_job_started(self, *, job_id: str) -> None:
        await self.update_import_job(
            job_id=job_id,
            status="parsing",
            started_at=datetime.now(UTC),
            error_message="",
        )

    async def create_import_row(
        self,
        *,
        import_job_id: str,
        row_number: int,
        raw_data: dict[str, object],
        parsed_email: str | None,
        status: str,
        contact_id: str | None,
        error_reason: str | None,
    ) -> ImportRow:
        row = ImportRow(
            import_job_id=import_job_id,
            row_number=row_number,
            raw_data=raw_data,
            parsed_email=parsed_email,
            status=status,
            contact_id=contact_id,
            error_reason=error_reason,
            processed_at=datetime.now(UTC),
        )
        self.session.add(row)
        await self.session.flush()
        return row

    async def list_sample_error_rows(
        self,
        *,
        import_job_id: str,
        limit: int = 10,
    ) -> list[ImportRow]:
        return await self.list_error_rows(
            import_job_id=import_job_id,
            limit=limit,
            offset=0,
        )

    async def list_error_rows(
        self,
        *,
        import_job_id: str,
        limit: int = 100,
        offset: int = 0,
    ) -> list[ImportRow]:
        stmt = (
            select(ImportRow)
            .where(ImportRow.import_job_id == import_job_id)
            .where(ImportRow.status.in_(("invalid", "suppressed", "duplicate", "errored")))
            .order_by(ImportRow.row_number.asc())
            .offset(offset)
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())
