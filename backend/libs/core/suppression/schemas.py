from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from libs.core.suppression.models import SuppressionEntry

SuppressionReasonCode = Literal[
    "hard_bounce",
    "complaint",
    "unsubscribe",
    "manual",
    "spam_trap",
    "role_account",
    "global_suppression_sync",
]

StoredSuppressionReasonCode = Literal[
    "hard_bounce",
    "soft_bounce_limit",
    "complaint",
    "unsubscribe",
    "manual",
    "spam_trap",
    "invalid",
    "global_blocklist",
]


class SuppressionCreateRequest(BaseModel):
    email: str = Field(min_length=5, max_length=320)
    reason_code: SuppressionReasonCode
    source: str = Field(default="manual_api", min_length=2, max_length=80)
    expires_at: datetime | None = None
    source_event_id: str | None = Field(default=None, max_length=64)
    campaign_id: str | None = Field(default=None, max_length=64)
    notes: str | None = Field(default=None, max_length=1000)
    sync_to_ses: bool = True


class SuppressionDeleteRequest(BaseModel):
    justification: str = Field(min_length=5, max_length=1000)


class SuppressionEntryResponse(BaseModel):
    id: str
    email: str
    reason_code: SuppressionReasonCode
    source: str
    first_suppressed_at: datetime
    expires_at: datetime | None

    @classmethod
    def from_model(
        cls,
        entry: SuppressionEntry,
        *,
        reason_code: SuppressionReasonCode,
        source: str,
    ) -> SuppressionEntryResponse:
        return cls(
            id=entry.id,
            email=entry.email,
            reason_code=reason_code,
            source=source,
            first_suppressed_at=entry.created_at,
            expires_at=entry.expires_at,
        )


class SuppressionListResponse(BaseModel):
    items: list[SuppressionEntryResponse]
    total: int
    limit: int
    offset: int


class SuppressionQueryParams(BaseModel):
    limit: int = Field(default=50, ge=1, le=200)
    offset: int = Field(default=0, ge=0)
    reason_code: SuppressionReasonCode | None = None


class SuppressionBulkImportResponse(BaseModel):
    imported_count: int
    skipped_count: int
    invalid_count: int
    total_rows: int


class SuppressionSesSyncSummary(BaseModel):
    pushed_count: int
    pulled_count: int
    scanned_remote_count: int
    error_count: int


class SuppressionRevealResponse(BaseModel):
    id: str
    email: str
