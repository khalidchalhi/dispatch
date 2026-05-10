from __future__ import annotations

import csv
import io
import re
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path
from typing import Protocol, TypedDict, cast
from uuid import uuid4

import dns.asyncresolver
from dns.exception import DNSException
from redis import asyncio as redis_async

from libs.core.auth.repository import AuthRepository
from libs.core.auth.schemas import CurrentActor
from libs.core.config import Settings, get_settings
from libs.core.contacts.repository import ContactRepository
from libs.core.db.session import get_session_factory
from libs.core.db.uow import UnitOfWork
from libs.core.errors import ConflictError, NotFoundError, PermissionDeniedError, ValidationError
from libs.core.imports.models import ImportJob, ImportRow
from libs.core.imports.repository import ImportRepository
from libs.core.imports.schemas import ImportJobResponse, ImportJobStatus, ImportRunSummary
from libs.core.lists.repository import ListRepository
from libs.core.logging import get_logger

logger = get_logger("core.imports")

_EMAIL_PATTERN = re.compile(
    r"^[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+$"
)


class ObjectStore(Protocol):
    async def put_bytes(self, *, key: str, data: bytes) -> None: ...

    async def get_bytes(self, *, key: str) -> bytes: ...


class MXLookupAdapter(Protocol):
    async def has_mx(self, domain: str) -> bool: ...


class LocalObjectStore:
    def __init__(self, root: str) -> None:
        self._root = Path(root).resolve()
        self._root.mkdir(parents=True, exist_ok=True)

    async def put_bytes(self, *, key: str, data: bytes) -> None:
        path = (self._root / key).resolve()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)

    async def get_bytes(self, *, key: str) -> bytes:
        path = (self._root / key).resolve()
        if not path.exists():
            raise NotFoundError("Import object not found")
        return path.read_bytes()


class DnsMxLookupAdapter:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._resolver = dns.asyncresolver.Resolver(configure=True)
        self._resolver.lifetime = 1.0
        self._resolver.timeout = 1.0
        self._fallback_cache: dict[str, tuple[bool, float]] = {}
        self._redis = redis_async.Redis.from_url(
            settings.redis_url,
            decode_responses=True,
        )

    def _cache_key(self, domain: str) -> str:
        return f"imports:mx:{domain.lower()}"

    async def has_mx(self, domain: str) -> bool:
        normalized = domain.strip().lower()
        if not normalized:
            return False

        cached = await self._cache_get(normalized)
        if cached is not None:
            return cached

        has_mx = await self._lookup_mx(normalized)
        await self._cache_set(normalized, has_mx)
        return has_mx

    async def _lookup_mx(self, domain: str) -> bool:
        try:
            answers = await self._resolver.resolve(domain, "MX")
        except DNSException:
            return False
        except Exception:
            logger.warning("imports.mx_lookup.error", domain=domain)
            return False
        return len(list(answers)) > 0

    async def _cache_get(self, domain: str) -> bool | None:
        now = time.time()
        fallback_item = self._fallback_cache.get(domain)
        if fallback_item is not None and fallback_item[1] > now:
            return fallback_item[0]

        try:
            raw = await self._redis.get(self._cache_key(domain))
        except Exception:
            return None
        if raw is None:
            return None
        return str(raw) == "1"

    async def _cache_set(self, domain: str, value: bool) -> None:
        expires_at = time.time() + self._settings.import_mx_cache_ttl_seconds
        self._fallback_cache[domain] = (value, expires_at)
        try:
            await self._redis.set(
                self._cache_key(domain),
                "1" if value else "0",
                ex=self._settings.import_mx_cache_ttl_seconds,
            )
        except Exception:
            logger.warning("imports.mx_cache.write_failed", domain=domain)


@dataclass(slots=True)
class _RowCounters:
    total_rows: int = 0
    valid_rows: int = 0
    invalid_rows: int = 0
    duplicate_rows: int = 0
    suppressed_rows: int = 0
    gate1_rejections: int = 0
    gate2_rejections: int = 0
    gate3_rejections: int = 0


class _ContactFieldValues(TypedDict):
    first_name: str | None
    last_name: str | None
    company: str | None
    title: str | None
    phone: str | None
    country_code: str | None
    timezone: str | None
    custom_attributes: dict[str, object]


class ImportService:
    def __init__(
        self,
        settings: Settings,
        *,
        object_store: ObjectStore | None = None,
        mx_lookup: MXLookupAdapter | None = None,
    ) -> None:
        self._settings = settings
        self._session_factory = get_session_factory()
        self._object_store = object_store or LocalObjectStore(settings.import_storage_root)
        self._mx_lookup = mx_lookup or DnsMxLookupAdapter(settings)

    async def create_import_job(
        self,
        *,
        actor: CurrentActor,
        file_name: str,
        file_bytes: bytes,
        source_label: str | None,
        target_list_id: str | None,
        ip_address: str | None,
        user_agent: str | None,
    ) -> ImportJob:
        self._require_admin(actor)
        normalized_file_name = file_name.strip() or "import.csv"
        if len(file_bytes) == 0:
            raise ValidationError("Import file is empty")
        if len(file_bytes) > self._settings.import_max_upload_bytes:
            raise ValidationError("Import file exceeds upload size limit")

        object_key = f"imports/{actor.user.id}/{uuid4().hex}.csv"
        await self._object_store.put_bytes(key=object_key, data=file_bytes)

        async with UnitOfWork(self._session_factory) as uow:
            repo = ImportRepository(uow.require_session())
            active_jobs = await repo.count_active_jobs_for_user(actor.user.id)
            if active_jobs >= self._settings.import_max_concurrent_jobs_per_user:
                raise ConflictError("Too many active imports for this user")

            if target_list_id is not None:
                list_repo = ListRepository(uow.require_session())
                list_entity = await list_repo.get_list_by_id(target_list_id)
                if list_entity is None:
                    raise NotFoundError("Target list not found")

            job = await repo.create_import_job(
                created_by=actor.user.id,
                file_name=normalized_file_name,
                file_s3_key=object_key,
                file_size_bytes=len(file_bytes),
                column_mapping=self._default_column_mapping(),
                source_label=self._clean_optional_text(source_label),
                target_list_id=target_list_id,
            )
            await AuthRepository(uow.require_session()).write_audit_log(
                actor_type=actor.actor_type,
                actor_id=actor.user.id,
                action="import.job.create",
                resource_type="import_job",
                resource_id=job.id,
                after_state={
                    "file_name": normalized_file_name,
                    "file_size_bytes": len(file_bytes),
                    "target_list_id": target_list_id,
                },
                ip_address=ip_address,
                user_agent=user_agent,
            )
            return job

    async def get_import_job(self, *, actor: CurrentActor, job_id: str) -> ImportJobResponse:
        self._require_admin(actor)
        async with self._session_factory() as session:
            repo = ImportRepository(session)
            job = await repo.get_import_job_by_id(job_id)
            if job is None:
                raise NotFoundError("Import job not found")
            sample_error_rows = await repo.list_sample_error_rows(import_job_id=job.id, limit=20)
            return ImportJobResponse.from_model(job, sample_error_rows=sample_error_rows)

    async def get_import_job_error_rows(
        self,
        *,
        actor: CurrentActor,
        job_id: str,
        limit: int = 200,
        offset: int = 0,
    ) -> list[ImportRow]:
        self._require_admin(actor)
        async with self._session_factory() as session:
            repo = ImportRepository(session)
            job = await repo.get_import_job_by_id(job_id)
            if job is None:
                raise NotFoundError("Import job not found")
            return await repo.list_error_rows(
                import_job_id=job.id,
                limit=limit,
                offset=offset,
            )

    async def run_import_job(self, *, job_id: str) -> ImportRunSummary:
        initial = await self._load_job(job_id)
        if initial.status != "queued":
            return ImportRunSummary(
                job_id=initial.id,
                status=cast(ImportJobStatus, initial.status),
                total_rows=initial.total_rows or 0,
                valid_rows=initial.valid_rows,
                invalid_rows=initial.invalid_rows,
                duplicate_rows=initial.duplicate_rows,
                suppressed_rows=initial.suppressed_rows,
                rows_per_second=0.0,
            )

        await self._mark_job_started(initial.id)
        try:
            csv_bytes = await self._object_store.get_bytes(key=initial.file_s3_key)
            reader, header_names = self._build_csv_reader(csv_bytes)
            mapping = self._resolve_column_mapping(initial.column_mapping)
            self._validate_required_columns(header_names, mapping)
            return await self._process_rows(
                job=initial,
                reader=reader,
                header_names=header_names,
                mapping=mapping,
            )
        except Exception as exc:
            await self._mark_job_failed(initial.id, error_message=str(exc))
            await self._write_completion_audit(
                job_id=initial.id,
                action="import.job.failed",
                after_state={"error_message": str(exc)},
            )
            raise

    async def _process_rows(
        self,
        *,
        job: ImportJob,
        reader: csv.DictReader[str],
        header_names: list[str],
        mapping: dict[str, str],
    ) -> ImportRunSummary:
        counters = _RowCounters()
        seen_emails: set[str] = set()
        batch_rows = 0
        list_membership_updated = False
        started_monotonic = time.perf_counter()
        batch_started_monotonic = started_monotonic

        async with UnitOfWork(self._session_factory) as uow:
            import_repo = ImportRepository(uow.require_session())
            contact_repo = ContactRepository(uow.require_session())
            list_repo = ListRepository(uow.require_session())
            await import_repo.update_import_job(job_id=job.id, status="validating")

            for row_number, row in enumerate(reader, start=1):
                counters.total_rows += 1
                batch_rows += 1
                raw_row = self._coerce_raw_row(row=row, header_names=header_names)
                parsed_email = self._clean_optional_text(raw_row.get(mapping["email"]))

                gate1_email = self._validate_gate1_email(parsed_email)
                if gate1_email is None:
                    counters.invalid_rows += 1
                    counters.gate1_rejections += 1
                    await import_repo.create_import_row(
                        import_job_id=job.id,
                        row_number=row_number,
                        raw_data=raw_row,
                        parsed_email=parsed_email,
                        status="invalid",
                        contact_id=None,
                        error_reason="gate1_invalid_format",
                    )
                    continue

                local_part, _, domain = gate1_email.partition("@")
                if domain in self._settings.disposable_domain_set:
                    counters.invalid_rows += 1
                    counters.gate1_rejections += 1
                    await import_repo.create_import_row(
                        import_job_id=job.id,
                        row_number=row_number,
                        raw_data=raw_row,
                        parsed_email=gate1_email,
                        status="invalid",
                        contact_id=None,
                        error_reason="gate1_disposable_domain",
                    )
                    continue

                has_mx = await self._mx_lookup.has_mx(domain)
                if not has_mx:
                    counters.invalid_rows += 1
                    counters.gate2_rejections += 1
                    await import_repo.create_import_row(
                        import_job_id=job.id,
                        row_number=row_number,
                        raw_data=raw_row,
                        parsed_email=gate1_email,
                        status="invalid",
                        contact_id=None,
                        error_reason="gate2_no_mx",
                    )
                    continue

                if self._settings.import_smtp_probe_enabled:
                    smtp_ok = await self._smtp_probe(gate1_email)
                    if not smtp_ok:
                        counters.invalid_rows += 1
                        counters.gate2_rejections += 1
                        await import_repo.create_import_row(
                            import_job_id=job.id,
                            row_number=row_number,
                            raw_data=raw_row,
                            parsed_email=gate1_email,
                            status="invalid",
                            contact_id=None,
                            error_reason="gate2_smtp_probe_failed",
                        )
                        continue

                role_prefix = local_part.split("+", 1)[0].lower()
                if role_prefix in self._settings.role_account_prefix_set:
                    counters.suppressed_rows += 1
                    counters.gate3_rejections += 1
                    await import_repo.create_import_row(
                        import_job_id=job.id,
                        row_number=row_number,
                        raw_data=raw_row,
                        parsed_email=gate1_email,
                        status="suppressed",
                        contact_id=None,
                        error_reason="gate3_role_account",
                    )
                    continue

                if gate1_email in seen_emails:
                    counters.duplicate_rows += 1
                    await import_repo.create_import_row(
                        import_job_id=job.id,
                        row_number=row_number,
                        raw_data=raw_row,
                        parsed_email=gate1_email,
                        status="duplicate",
                        contact_id=None,
                        error_reason="duplicate_in_file",
                    )
                    continue
                seen_emails.add(gate1_email)

                contact_fields = self._extract_contact_fields(raw_row=raw_row, mapping=mapping)
                existing_contact = await contact_repo.get_contact_by_email(gate1_email)
                if existing_contact is None:
                    contact = await contact_repo.create_contact(
                        email=gate1_email,
                        email_domain=domain,
                        first_name=contact_fields["first_name"],
                        last_name=contact_fields["last_name"],
                        company=contact_fields["company"],
                        title=contact_fields["title"],
                        phone=contact_fields["phone"],
                        country_code=contact_fields["country_code"],
                        timezone=contact_fields["timezone"],
                        custom_attributes=contact_fields["custom_attributes"],
                    )
                    await contact_repo.upsert_subscription_status(
                        contact_id=contact.id,
                        channel="email",
                        status="subscribed",
                        reason="csv_import",
                    )
                    await contact_repo.upsert_preferences(
                        contact_id=contact.id,
                        campaign_types=[],
                        max_frequency_per_week=None,
                        language="en",
                    )
                else:
                    contact = existing_contact
                    update_values = self._build_update_values(contact_fields)
                    if update_values:
                        await contact_repo.update_contact(
                            contact_id=contact.id,
                            values=update_values,
                        )

                await contact_repo.create_contact_source(
                    contact_id=contact.id,
                    source_type="csv_import",
                    source_detail=f"import_job:{job.id}:row:{row_number}",
                    source_list=job.source_label,
                )
                if job.target_list_id is not None and contact.lifecycle_status == "active":
                    await list_repo.add_membership(
                        list_id=job.target_list_id,
                        contact_id=contact.id,
                    )
                    list_membership_updated = True

                counters.valid_rows += 1
                await import_repo.create_import_row(
                    import_job_id=job.id,
                    row_number=row_number,
                    raw_data=raw_row,
                    parsed_email=gate1_email,
                    status="upserted",
                    contact_id=contact.id,
                    error_reason=None,
                )

                if batch_rows >= self._settings.import_batch_size:
                    self._log_batch_summary(
                        job_id=job.id,
                        batch_rows=batch_rows,
                        counters=counters,
                        batch_started_monotonic=batch_started_monotonic,
                    )
                    batch_rows = 0
                    batch_started_monotonic = time.perf_counter()

            if batch_rows > 0:
                self._log_batch_summary(
                    job_id=job.id,
                    batch_rows=batch_rows,
                    counters=counters,
                    batch_started_monotonic=batch_started_monotonic,
                )

            if list_membership_updated and job.target_list_id is not None:
                await list_repo.refresh_member_count(list_id=job.target_list_id)

            await import_repo.update_import_job(
                job_id=job.id,
                status="complete",
                total_rows=counters.total_rows,
                valid_rows=counters.valid_rows,
                invalid_rows=counters.invalid_rows,
                duplicate_rows=counters.duplicate_rows,
                suppressed_rows=counters.suppressed_rows,
                completed_at=datetime.now(UTC),
            )

            total_elapsed = max(time.perf_counter() - started_monotonic, 0.0001)
            rows_per_second = counters.total_rows / total_elapsed
            audit_after_state: dict[str, object] = {
                "total_rows": counters.total_rows,
                "valid_rows": counters.valid_rows,
                "invalid_rows": counters.invalid_rows,
                "duplicate_rows": counters.duplicate_rows,
                "suppressed_rows": counters.suppressed_rows,
                "rows_per_second": rows_per_second,
                "rejection_rate_gate1": self._ratio(
                    counters.gate1_rejections,
                    counters.total_rows,
                ),
                "rejection_rate_gate2": self._ratio(
                    counters.gate2_rejections,
                    counters.total_rows,
                ),
                "rejection_rate_gate3": self._ratio(
                    counters.gate3_rejections,
                    counters.total_rows,
                ),
            }
            await AuthRepository(uow.require_session()).write_audit_log(
                actor_type="system",
                actor_id=None,
                action="import.job.complete",
                resource_type="import_job",
                resource_id=job.id,
                after_state=audit_after_state,
                ip_address=None,
                user_agent="celery:imports.run_import",
            )

            logger.info(
                "imports.job.complete",
                job_id=job.id,
                total_rows=counters.total_rows,
                valid_rows=counters.valid_rows,
                invalid_rows=counters.invalid_rows,
                duplicate_rows=counters.duplicate_rows,
                suppressed_rows=counters.suppressed_rows,
                rows_per_second=rows_per_second,
            )
            return ImportRunSummary(
                job_id=job.id,
                status="complete",
                total_rows=counters.total_rows,
                valid_rows=counters.valid_rows,
                invalid_rows=counters.invalid_rows,
                duplicate_rows=counters.duplicate_rows,
                suppressed_rows=counters.suppressed_rows,
                rows_per_second=rows_per_second,
            )

    async def _load_job(self, job_id: str) -> ImportJob:
        async with self._session_factory() as session:
            repo = ImportRepository(session)
            job = await repo.get_import_job_by_id(job_id)
            if job is None:
                raise NotFoundError("Import job not found")
            return job

    async def _mark_job_started(self, job_id: str) -> None:
        async with UnitOfWork(self._session_factory) as uow:
            await ImportRepository(uow.require_session()).mark_job_started(job_id=job_id)

    async def _mark_job_failed(self, job_id: str, *, error_message: str) -> None:
        async with UnitOfWork(self._session_factory) as uow:
            await ImportRepository(uow.require_session()).update_import_job(
                job_id=job_id,
                status="failed",
                error_message=error_message[:4000],
                completed_at=datetime.now(UTC),
            )
        logger.exception("imports.job.failed", job_id=job_id, error=error_message)

    async def _write_completion_audit(
        self,
        *,
        job_id: str,
        action: str,
        after_state: dict[str, object],
    ) -> None:
        async with UnitOfWork(self._session_factory) as uow:
            await AuthRepository(uow.require_session()).write_audit_log(
                actor_type="system",
                actor_id=None,
                action=action,
                resource_type="import_job",
                resource_id=job_id,
                after_state=after_state,
                ip_address=None,
                user_agent="celery:imports.run_import",
            )

    @staticmethod
    def _default_column_mapping() -> dict[str, object]:
        return {
            "email": "email",
            "first_name": "first_name",
            "last_name": "last_name",
            "company": "company",
            "title": "title",
            "phone": "phone",
            "country_code": "country_code",
            "timezone": "timezone",
        }

    @staticmethod
    def _resolve_column_mapping(column_mapping: dict[str, object]) -> dict[str, str]:
        resolved: dict[str, str] = {}
        for key, value in column_mapping.items():
            if isinstance(value, str):
                resolved[key] = value
        if "email" not in resolved:
            resolved["email"] = "email"
        return resolved

    @staticmethod
    def _build_csv_reader(file_bytes: bytes) -> tuple[csv.DictReader[str], list[str]]:
        try:
            decoded = file_bytes.decode("utf-8-sig")
        except UnicodeDecodeError as exc:
            raise ValidationError("Import file must be valid UTF-8 CSV") from exc

        stream = io.StringIO(decoded, newline="")
        try:
            reader = csv.DictReader(stream, strict=True)
        except csv.Error as exc:
            raise ValidationError("Invalid CSV content") from exc
        if reader.fieldnames is None:
            raise ValidationError("CSV header row is required")
        header_names = [header.strip() for header in reader.fieldnames if header]
        return reader, header_names

    @staticmethod
    def _validate_required_columns(header_names: list[str], mapping: dict[str, str]) -> None:
        required_column = mapping["email"]
        if required_column not in header_names:
            raise ValidationError(f"CSV is missing required column: {required_column}")

    @staticmethod
    def _coerce_raw_row(
        *,
        row: dict[str, str | None],
        header_names: list[str],
    ) -> dict[str, object]:
        coerced: dict[str, object] = {}
        for header in header_names:
            value = row.get(header)
            coerced[header] = value if value is not None else ""
        return coerced

    def _validate_gate1_email(self, parsed_email: str | None) -> str | None:
        if parsed_email is None:
            return None
        normalized = parsed_email.strip().lower()
        if "@" not in normalized:
            return None
        if not _EMAIL_PATTERN.match(normalized):
            return None
        return normalized

    @staticmethod
    def _build_update_values(contact_fields: _ContactFieldValues) -> dict[str, object]:
        values: dict[str, object] = {}
        for key in (
            "first_name",
            "last_name",
            "company",
            "title",
            "phone",
            "country_code",
            "timezone",
        ):
            value = contact_fields[key]
            if isinstance(value, str) and value:
                values[key] = value
        custom_attributes = contact_fields["custom_attributes"]
        if isinstance(custom_attributes, dict) and custom_attributes:
            values["custom_attributes"] = custom_attributes
        return values

    def _extract_contact_fields(
        self,
        *,
        raw_row: dict[str, object],
        mapping: dict[str, str],
    ) -> _ContactFieldValues:
        known_mapping_values = {value for value in mapping.values()}
        first_name = self._clean_optional_text(raw_row.get(mapping.get("first_name", "first_name")))
        last_name = self._clean_optional_text(raw_row.get(mapping.get("last_name", "last_name")))
        company = self._clean_optional_text(raw_row.get(mapping.get("company", "company")))
        title = self._clean_optional_text(raw_row.get(mapping.get("title", "title")))
        phone = self._clean_optional_text(raw_row.get(mapping.get("phone", "phone")))
        country_code = self._clean_optional_text(
            raw_row.get(mapping.get("country_code", "country_code"))
        )
        timezone = self._clean_optional_text(raw_row.get(mapping.get("timezone", "timezone")))
        custom_attributes: dict[str, object] = {}
        for key, value in raw_row.items():
            if key in known_mapping_values:
                continue
            cleaned = self._clean_optional_text(value)
            if cleaned is not None:
                custom_attributes[key] = cleaned
        return {
            "first_name": first_name,
            "last_name": last_name,
            "company": company,
            "title": title,
            "phone": phone,
            "country_code": country_code,
            "timezone": timezone,
            "custom_attributes": custom_attributes,
        }

    async def _smtp_probe(self, email: str) -> bool:
        logger.info("imports.smtp_probe.skipped", email_hash=self._email_hash(email))
        return True

    @staticmethod
    def _ratio(numerator: int, denominator: int) -> float:
        if denominator == 0:
            return 0.0
        return numerator / denominator

    def _log_batch_summary(
        self,
        *,
        job_id: str,
        batch_rows: int,
        counters: _RowCounters,
        batch_started_monotonic: float,
    ) -> None:
        elapsed = max(time.perf_counter() - batch_started_monotonic, 0.0001)
        logger.info(
            "imports.batch.processed",
            job_id=job_id,
            batch_rows=batch_rows,
            total_rows=counters.total_rows,
            valid_rows=counters.valid_rows,
            invalid_rows=counters.invalid_rows,
            duplicate_rows=counters.duplicate_rows,
            suppressed_rows=counters.suppressed_rows,
            rows_per_second=batch_rows / elapsed,
        )

    @staticmethod
    def _email_hash(email: str) -> str:
        import hashlib

        return hashlib.sha256(email.encode("utf-8")).hexdigest()

    @staticmethod
    def _clean_optional_text(value: object) -> str | None:
        if value is None:
            return None
        if not isinstance(value, str):
            return None
        cleaned = value.strip()
        return cleaned if cleaned else None

    @staticmethod
    def _require_admin(actor: CurrentActor) -> None:
        if actor.user.role != "admin":
            raise PermissionDeniedError("Admin role required")


@lru_cache(maxsize=1)
def get_import_service() -> ImportService:
    return ImportService(get_settings())


def reset_import_service_cache() -> None:
    get_import_service.cache_clear()
