from __future__ import annotations

import asyncio
import csv
import hashlib
import io
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from functools import lru_cache
from typing import Protocol, cast

from redis import asyncio as redis_async

from libs.core.auth.repository import AuthRepository
from libs.core.auth.schemas import CurrentActor
from libs.core.config import Settings, get_settings
from libs.core.db.session import get_session_factory
from libs.core.db.uow import UnitOfWork
from libs.core.errors import NotFoundError, PermissionDeniedError, RateLimitedError, ValidationError
from libs.core.logging import get_logger
from libs.core.suppression.models import SuppressionEntry
from libs.core.suppression.repository import SuppressionRepository
from libs.core.suppression.schemas import (
    SuppressionCreateRequest,
    SuppressionQueryParams,
    SuppressionReasonCode,
    SuppressionSesSyncSummary,
)

logger = get_logger("core.suppression")

_STORED_TO_CANONICAL_REASON: dict[str, SuppressionReasonCode] = {
    "hard_bounce": "hard_bounce",
    "soft_bounce_limit": "hard_bounce",
    "complaint": "complaint",
    "unsubscribe": "unsubscribe",
    "manual": "manual",
    "spam_trap": "spam_trap",
    "invalid": "role_account",
    "global_blocklist": "global_suppression_sync",
}
_CANONICAL_TO_STORED_REASON: dict[SuppressionReasonCode, str] = {
    "hard_bounce": "hard_bounce",
    "complaint": "complaint",
    "unsubscribe": "unsubscribe",
    "manual": "manual",
    "spam_trap": "spam_trap",
    "role_account": "invalid",
    "global_suppression_sync": "global_blocklist",
}
_SOURCE_PREFIX = "source="


@dataclass(frozen=True, slots=True)
class RemoteSuppressedDestination:
    email: str
    reason_code: SuppressionReasonCode


class SuppressionSyncAdapter(Protocol):
    async def put_suppressed_destination(
        self,
        *,
        email: str,
        reason_code: SuppressionReasonCode,
    ) -> None:
        ...

    async def get_suppressed_destination(
        self,
        *,
        email: str,
    ) -> RemoteSuppressedDestination | None: ...

    async def list_suppressed_destinations(
        self,
        *,
        page_size: int,
        next_token: str | None = None,
    ) -> tuple[list[RemoteSuppressedDestination], str | None]:
        ...

    async def delete_suppressed_destination(self, *, email: str) -> None: ...


class NoopSuppressionSyncAdapter:
    async def put_suppressed_destination(
        self,
        *,
        email: str,
        reason_code: SuppressionReasonCode,
    ) -> None:
        _ = (email, reason_code)

    async def get_suppressed_destination(self, *, email: str) -> RemoteSuppressedDestination | None:
        _ = email
        return None

    async def list_suppressed_destinations(
        self,
        *,
        page_size: int,
        next_token: str | None = None,
    ) -> tuple[list[RemoteSuppressedDestination], str | None]:
        _ = (page_size, next_token)
        return ([], None)

    async def delete_suppressed_destination(self, *, email: str) -> None:
        _ = email


@dataclass(slots=True)
class SuppressionListResult:
    items: list[SuppressionEntry]
    total: int
    limit: int
    offset: int


@dataclass(slots=True)
class SuppressionBulkImportResult:
    imported_count: int
    skipped_count: int
    invalid_count: int
    total_rows: int


class SuppressionService:
    def __init__(
        self,
        settings: Settings,
        *,
        sync_adapter: SuppressionSyncAdapter | None = None,
    ) -> None:
        self._settings = settings
        self._session_factory = get_session_factory()
        self._sync_adapter = sync_adapter or NoopSuppressionSyncAdapter()
        self._redis = cast(
            redis_async.Redis,
            redis_async.from_url(settings.redis_url, decode_responses=True),  # type: ignore[no-untyped-call]
        )
        self._cache_fallback: dict[str, tuple[bool, float]] = {}

    async def is_suppressed(self, email: str) -> bool:
        normalized_email = self._normalize_email(email)
        cached = await self._cache_get(normalized_email)
        if cached is not None:
            return cached

        async with self._session_factory() as session:
            repo = SuppressionRepository(session)
            entry = await repo.get_active_by_email(normalized_email)
            suppressed = entry is not None
            await self._cache_set(normalized_email, suppressed)
            return suppressed

    async def list_suppressions(
        self,
        *,
        actor: CurrentActor,
        query: SuppressionQueryParams,
    ) -> SuppressionListResult:
        self._require_admin(actor)
        stored_reason = (
            _CANONICAL_TO_STORED_REASON[query.reason_code]
            if query.reason_code is not None
            else None
        )
        async with self._session_factory() as session:
            repo = SuppressionRepository(session)
            items = await repo.list_entries(
                limit=query.limit,
                offset=query.offset,
                stored_reason=stored_reason,
            )
            total = await repo.count_entries(stored_reason=stored_reason)
            return SuppressionListResult(
                items=items,
                total=total,
                limit=query.limit,
                offset=query.offset,
            )

    async def get_suppression(
        self,
        *,
        actor: CurrentActor,
        email: str,
    ) -> SuppressionEntry:
        self._require_admin(actor)
        normalized_email = self._normalize_email(email)
        async with self._session_factory() as session:
            repo = SuppressionRepository(session)
            entry = await repo.get_by_email(normalized_email)
            if entry is None:
                raise NotFoundError("Suppression entry not found")
            return entry

    async def get_suppression_by_id(
        self,
        *,
        actor: CurrentActor,
        entry_id: str,
    ) -> SuppressionEntry:
        self._require_admin(actor)
        async with self._session_factory() as session:
            repo = SuppressionRepository(session)
            entry = await repo.get_by_id(entry_id)
            if entry is None:
                raise NotFoundError("Suppression entry not found")
            return entry

    async def list_export_entries(
        self,
        *,
        actor: CurrentActor,
        reason_code: SuppressionReasonCode | None = None,
    ) -> list[SuppressionEntry]:
        self._require_admin(actor)
        stored_reason = (
            _CANONICAL_TO_STORED_REASON[reason_code] if reason_code is not None else None
        )
        page_size = 500
        offset = 0
        items: list[SuppressionEntry] = []
        async with self._session_factory() as session:
            repo = SuppressionRepository(session)
            while True:
                page = await repo.list_active_entries(limit=page_size, offset=offset)
                if stored_reason is not None:
                    page = [entry for entry in page if entry.reason == stored_reason]
                if not page:
                    break
                items.extend(page)
                offset += len(page)
        return items

    async def add_suppression(
        self,
        *,
        actor: CurrentActor,
        payload: SuppressionCreateRequest,
        ip_address: str | None,
        user_agent: str | None,
    ) -> SuppressionEntry:
        self._require_admin(actor)
        normalized_email = self._normalize_email(payload.email)
        normalized_source = self._normalize_source(payload.source)
        stored_reason = _CANONICAL_TO_STORED_REASON[payload.reason_code]
        note_blob = self._build_note_blob(source=normalized_source, notes=payload.notes)
        email_hash = self._email_hash(normalized_email)

        async with UnitOfWork(self._session_factory) as uow:
            repo = SuppressionRepository(uow.require_session())
            existing = await repo.get_by_email(normalized_email)
            if existing is None:
                entry = await repo.create_entry(
                    email=normalized_email,
                    reason=stored_reason,
                    source_event_id=payload.source_event_id,
                    campaign_id=payload.campaign_id,
                    notes=note_blob,
                    expires_at=payload.expires_at,
                )
                action = "suppression.add"
                before_state: dict[str, object] | None = None
            else:
                before_state = {
                    "reason_code": self.to_reason_code(existing),
                    "expires_at": existing.expires_at.isoformat() if existing.expires_at else None,
                }
                await repo.update_entry(
                    entry_id=existing.id,
                    values={
                        "reason": stored_reason,
                        "source_event_id": payload.source_event_id,
                        "campaign_id": payload.campaign_id,
                        "notes": note_blob,
                        "expires_at": payload.expires_at,
                    },
                )
                refreshed = await repo.get_by_id(existing.id)
                if refreshed is None:
                    raise NotFoundError("Suppression entry not found")
                entry = refreshed
                action = "suppression.update"

            await AuthRepository(uow.require_session()).write_audit_log(
                actor_type=actor.actor_type,
                actor_id=actor.user.id,
                action=action,
                resource_type="suppression_entry",
                resource_id=entry.id,
                before_state=before_state,
                after_state={
                    "email_sha256": email_hash,
                    "reason_code": payload.reason_code,
                    "source": normalized_source,
                    "expires_at": payload.expires_at.isoformat() if payload.expires_at else None,
                },
                ip_address=ip_address,
                user_agent=user_agent,
            )

        await self._cache_delete(normalized_email)
        if payload.sync_to_ses:
            await self._try_push_to_ses(email=normalized_email, reason_code=payload.reason_code)
        return entry

    async def remove_suppression(
        self,
        *,
        actor: CurrentActor,
        email: str,
        justification: str,
        ip_address: str | None,
        user_agent: str | None,
        sync_to_ses: bool = True,
    ) -> None:
        self._require_admin(actor)
        normalized_email = self._normalize_email(email)
        cleaned_justification = justification.strip()
        if len(cleaned_justification) < 5:
            raise ValidationError("justification is required")

        day_start = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
        async with UnitOfWork(self._session_factory) as uow:
            repo = SuppressionRepository(uow.require_session())
            removals_today = await repo.count_audit_actions_since(
                action="suppression.remove",
                occurred_after=day_start,
            )
            if removals_today >= self._settings.suppression_max_removals_per_day:
                raise RateLimitedError("Manual suppression removal limit reached for today")

            existing = await repo.get_by_email(normalized_email)
            if existing is None:
                raise NotFoundError("Suppression entry not found")
            reason_code = self.to_reason_code(existing)

            deleted = await repo.delete_entry(entry_id=existing.id)
            if not deleted:
                raise NotFoundError("Suppression entry not found")

            await AuthRepository(uow.require_session()).write_audit_log(
                actor_type=actor.actor_type,
                actor_id=actor.user.id,
                action="suppression.remove",
                resource_type="suppression_entry",
                resource_id=existing.id,
                before_state={
                    "email_sha256": self._email_hash(normalized_email),
                    "reason_code": reason_code,
                    "first_suppressed_at": existing.created_at.isoformat(),
                },
                after_state={
                    "removed": True,
                    "justification": cleaned_justification,
                },
                ip_address=ip_address,
                user_agent=user_agent,
            )

        await self._cache_delete(normalized_email)
        if sync_to_ses:
            await self._try_delete_from_ses(normalized_email)

    async def bulk_import_csv(
        self,
        *,
        actor: CurrentActor,
        csv_bytes: bytes,
        reason_code: SuppressionReasonCode,
        source: str,
        ip_address: str | None,
        user_agent: str | None,
        sync_to_ses: bool = True,
    ) -> SuppressionBulkImportResult:
        self._require_admin(actor)
        rows = self._parse_csv_rows(csv_bytes)
        normalized_source = self._normalize_source(source)
        stored_reason = _CANONICAL_TO_STORED_REASON[reason_code]

        imported_count = 0
        skipped_count = 0
        invalid_count = 0
        total_rows = len(rows)
        touched_emails: list[str] = []
        seen_in_file: set[str] = set()

        async with UnitOfWork(self._session_factory) as uow:
            repo = SuppressionRepository(uow.require_session())
            auth_repo = AuthRepository(uow.require_session())
            for raw_email in rows:
                try:
                    normalized_email = self._normalize_email(raw_email)
                except ValidationError:
                    invalid_count += 1
                    continue

                if normalized_email in seen_in_file:
                    skipped_count += 1
                    continue
                seen_in_file.add(normalized_email)

                notes_blob = self._build_note_blob(source=normalized_source, notes=None)
                existing = await repo.get_by_email(normalized_email)
                if existing is None:
                    await repo.create_entry(
                        email=normalized_email,
                        reason=stored_reason,
                        source_event_id=None,
                        campaign_id=None,
                        notes=notes_blob,
                        expires_at=None,
                    )
                    imported_count += 1
                    touched_emails.append(normalized_email)
                    continue

                if existing.reason == stored_reason and (existing.notes or "") == notes_blob:
                    skipped_count += 1
                    continue

                await repo.update_entry(
                    entry_id=existing.id,
                    values={
                        "reason": stored_reason,
                        "notes": notes_blob,
                    },
                )
                imported_count += 1
                touched_emails.append(normalized_email)

            await auth_repo.write_audit_log(
                actor_type=actor.actor_type,
                actor_id=actor.user.id,
                action="suppression.bulk_import",
                resource_type="suppression_entry",
                resource_id=None,
                after_state={
                    "reason_code": reason_code,
                    "source": normalized_source,
                    "imported_count": imported_count,
                    "skipped_count": skipped_count,
                    "invalid_count": invalid_count,
                    "total_rows": total_rows,
                },
                ip_address=ip_address,
                user_agent=user_agent,
            )

        for email_item in touched_emails:
            await self._cache_delete(email_item)
            if sync_to_ses:
                await self._try_push_to_ses(email=email_item, reason_code=reason_code)

        return SuppressionBulkImportResult(
            imported_count=imported_count,
            skipped_count=skipped_count,
            invalid_count=invalid_count,
            total_rows=total_rows,
        )

    async def reconcile_with_ses(self) -> SuppressionSesSyncSummary:
        if not self._settings.suppression_ses_sync_enabled:
            return SuppressionSesSyncSummary(
                pushed_count=0,
                pulled_count=0,
                scanned_remote_count=0,
                error_count=0,
            )

        pushed_count = 0
        pulled_count = 0
        scanned_remote_count = 0
        error_count = 0

        max_records = self._settings.suppression_ses_sync_max_records_per_run
        batch_size = self._settings.suppression_ses_sync_batch_size
        push_limit = max_records

        offset = 0
        while pushed_count < push_limit:
            async with self._session_factory() as session:
                repo = SuppressionRepository(session)
                local_entries = await repo.list_active_entries(
                    limit=batch_size,
                    offset=offset,
                )
            if not local_entries:
                break

            for entry in local_entries:
                if pushed_count >= push_limit:
                    break
                reason_code = self.to_reason_code(entry)
                try:
                    await self._sync_adapter.put_suppressed_destination(
                        email=entry.email,
                        reason_code=reason_code,
                    )
                    pushed_count += 1
                except Exception:
                    error_count += 1
                    logger.warning(
                        "suppression.ses.push_failed",
                        email_sha256=self._email_hash(entry.email),
                    )
                await self._throttle_sync()
            offset += len(local_entries)

        next_token: str | None = None
        while scanned_remote_count < max_records:
            try:
                remote_entries, next_token = await self._sync_adapter.list_suppressed_destinations(
                    page_size=batch_size,
                    next_token=next_token,
                )
            except Exception:
                error_count += 1
                logger.warning("suppression.ses.pull_page_failed")
                break

            if not remote_entries:
                break

            scanned_remote_count += len(remote_entries)
            for remote_entry in remote_entries:
                if scanned_remote_count > max_records:
                    break
                try:
                    changed = await self._upsert_system_suppression(
                        email=remote_entry.email,
                        reason_code=remote_entry.reason_code,
                        source="ses_account_sync",
                    )
                    if changed:
                        pulled_count += 1
                except Exception:
                    error_count += 1
                    logger.warning(
                        "suppression.ses.pull_upsert_failed",
                        email_sha256=self._email_hash(remote_entry.email),
                    )
                await self._throttle_sync()

            if next_token is None:
                break

        return SuppressionSesSyncSummary(
            pushed_count=pushed_count,
            pulled_count=pulled_count,
            scanned_remote_count=scanned_remote_count,
            error_count=error_count,
        )

    async def upsert_system_suppression(
        self,
        *,
        email: str,
        reason_code: SuppressionReasonCode,
        source: str,
    ) -> bool:
        return await self._upsert_system_suppression(
            email=email,
            reason_code=reason_code,
            source=source,
        )

    def to_reason_code(self, entry: SuppressionEntry) -> SuppressionReasonCode:
        return _STORED_TO_CANONICAL_REASON.get(entry.reason, "manual")

    def to_source(self, entry: SuppressionEntry) -> str:
        source, _ = self._parse_note_blob(entry.notes)
        return source

    async def _upsert_system_suppression(
        self,
        *,
        email: str,
        reason_code: SuppressionReasonCode,
        source: str,
    ) -> bool:
        normalized_email = self._normalize_email(email)
        stored_reason = _CANONICAL_TO_STORED_REASON[reason_code]
        notes = self._build_note_blob(source=source, notes=None)

        async with UnitOfWork(self._session_factory) as uow:
            repo = SuppressionRepository(uow.require_session())
            existing = await repo.get_by_email(normalized_email)
            changed = False
            if existing is None:
                created = await repo.create_entry(
                    email=normalized_email,
                    reason=stored_reason,
                    source_event_id=None,
                    campaign_id=None,
                    notes=notes,
                    expires_at=None,
                )
                changed = True
                resource_id = created.id
            else:
                if existing.reason != stored_reason or (existing.notes or "") != notes:
                    await repo.update_entry(
                        entry_id=existing.id,
                        values={
                            "reason": stored_reason,
                            "notes": notes,
                        },
                    )
                    changed = True
                resource_id = existing.id

            if changed:
                await AuthRepository(uow.require_session()).write_audit_log(
                    actor_type="system",
                    actor_id=None,
                    action="suppression.sync.pull",
                    resource_type="suppression_entry",
                    resource_id=resource_id,
                    after_state={
                        "email_sha256": self._email_hash(normalized_email),
                        "reason_code": reason_code,
                        "source": source,
                    },
                    ip_address=None,
                    user_agent="worker:suppression.reconcile_with_ses",
                )

        if changed:
            await self._cache_delete(normalized_email)
        return changed

    async def _cache_get(self, email: str) -> bool | None:
        now = time.time()
        fallback = self._cache_fallback.get(email)
        if fallback is not None and fallback[1] > now:
            return fallback[0]
        if self._settings.app_env == "test":
            return None

        try:
            value = await self._redis.get(self._cache_key(email))
        except Exception:
            return None
        if value is None:
            return None
        return str(value) == "1"

    async def _cache_set(self, email: str, value: bool) -> None:
        ttl = self._settings.suppression_cache_ttl_seconds
        self._cache_fallback[email] = (value, time.time() + ttl)
        if self._settings.app_env == "test":
            return
        try:
            await self._redis.set(self._cache_key(email), "1" if value else "0", ex=ttl)
        except Exception:
            logger.warning("suppression.cache.write_failed")

    async def _cache_delete(self, email: str) -> None:
        self._cache_fallback.pop(email, None)
        if self._settings.app_env == "test":
            return
        try:
            await self._redis.delete(self._cache_key(email))
        except Exception:
            logger.warning("suppression.cache.delete_failed")

    def _cache_key(self, email: str) -> str:
        return f"suppression:{email.lower()}"

    async def _try_push_to_ses(self, *, email: str, reason_code: SuppressionReasonCode) -> None:
        if not self._settings.suppression_ses_sync_enabled:
            return
        try:
            await self._sync_adapter.put_suppressed_destination(
                email=email,
                reason_code=reason_code,
            )
        except Exception:
            logger.warning(
                "suppression.ses.push_failed",
                email_sha256=self._email_hash(email),
                reason_code=reason_code,
            )

    async def _try_delete_from_ses(self, email: str) -> None:
        if not self._settings.suppression_ses_sync_enabled:
            return
        try:
            await self._sync_adapter.delete_suppressed_destination(email=email)
        except Exception:
            logger.warning(
                "suppression.ses.delete_failed",
                email_sha256=self._email_hash(email),
            )

    async def _throttle_sync(self) -> None:
        if self._settings.suppression_ses_sync_pause_ms <= 0:
            return
        await asyncio.sleep(self._settings.suppression_ses_sync_pause_ms / 1000.0)

    @staticmethod
    def _normalize_email(value: str) -> str:
        normalized = value.strip().lower()
        if "@" not in normalized:
            raise ValidationError("Invalid email address")
        local, _, domain = normalized.partition("@")
        if not local or "." not in domain:
            raise ValidationError("Invalid email address")
        return normalized

    @staticmethod
    def _normalize_source(value: str) -> str:
        cleaned = value.strip().lower().replace(" ", "_")
        if len(cleaned) < 2:
            raise ValidationError("source is required")
        return cleaned[:80]

    @staticmethod
    def _build_note_blob(*, source: str, notes: str | None) -> str:
        trimmed_notes = notes.strip() if notes is not None else ""
        if trimmed_notes:
            return f"{_SOURCE_PREFIX}{source}\n{trimmed_notes}"
        return f"{_SOURCE_PREFIX}{source}"

    @staticmethod
    def _parse_note_blob(value: str | None) -> tuple[str, str | None]:
        if value is None or not value.strip():
            return ("unknown", None)
        line_one, _, remainder = value.partition("\n")
        if line_one.lower().startswith(_SOURCE_PREFIX):
            source = line_one[len(_SOURCE_PREFIX) :].strip() or "unknown"
            notes = remainder.strip() if remainder.strip() else None
            return (source, notes)
        return ("unknown", value.strip())

    @staticmethod
    def _email_hash(email: str) -> str:
        return hashlib.sha256(email.encode("utf-8")).hexdigest()

    @staticmethod
    def _parse_csv_rows(file_bytes: bytes) -> list[str]:
        try:
            decoded = file_bytes.decode("utf-8-sig")
        except UnicodeDecodeError as exc:
            raise ValidationError("CSV must be UTF-8") from exc

        reader = csv.DictReader(io.StringIO(decoded, newline=""), strict=True)
        if reader.fieldnames is None:
            raise ValidationError("CSV header row is required")

        header_by_lower = {header.strip().lower(): header for header in reader.fieldnames if header}
        email_header = header_by_lower.get("email")
        if email_header is None:
            raise ValidationError("CSV must include an email column")

        rows: list[str] = []
        for row in reader:
            value = row.get(email_header, "")
            rows.append(value if isinstance(value, str) else "")
        return rows

    @staticmethod
    def _require_admin(actor: CurrentActor) -> None:
        if actor.user.role != "admin":
            raise PermissionDeniedError("Admin role required")


@lru_cache(maxsize=1)
def get_suppression_service() -> SuppressionService:
    return SuppressionService(get_settings())


def reset_suppression_service_cache() -> None:
    get_suppression_service.cache_clear()
