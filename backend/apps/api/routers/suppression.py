from __future__ import annotations

import csv
import io
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, Query, Request, UploadFile, status
from fastapi.responses import StreamingResponse

from apps.api.deps import get_current_actor, get_suppression_service_dep, require_admin
from libs.core.auth.models import User
from libs.core.auth.schemas import CurrentActor
from libs.core.suppression.models import SuppressionEntry
from libs.core.suppression.schemas import (
    SuppressionBulkImportResponse,
    SuppressionCreateRequest,
    SuppressionDeleteRequest,
    SuppressionEntryResponse,
    SuppressionListResponse,
    SuppressionQueryParams,
    SuppressionRevealResponse,
    SuppressionReasonCode,
)
from libs.core.suppression.service import SuppressionService

router = APIRouter(prefix="/suppression", tags=["suppression"])


def _client_ip(request: Request) -> str | None:
    return request.client.host if request.client else None


def _to_response(entry: SuppressionEntry, service: SuppressionService) -> SuppressionEntryResponse:
    return SuppressionEntryResponse.from_model(
        entry,
        reason_code=service.to_reason_code(entry),
        source=service.to_source(entry),
    )


@router.get("", response_model=SuppressionListResponse)
async def list_suppressions(
    actor: Annotated[CurrentActor, Depends(get_current_actor)],
    _: Annotated[User, Depends(require_admin)],
    service: Annotated[SuppressionService, Depends(get_suppression_service_dep)],
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
    reason_code: SuppressionReasonCode | None = None,
) -> SuppressionListResponse:
    result = await service.list_suppressions(
        actor=actor,
        query=SuppressionQueryParams(limit=limit, offset=offset, reason_code=reason_code),
    )
    return SuppressionListResponse(
        items=[_to_response(item, service) for item in result.items],
        total=result.total,
        limit=result.limit,
        offset=result.offset,
    )


@router.post("/export")
async def export_suppressions(
    actor: Annotated[CurrentActor, Depends(get_current_actor)],
    _: Annotated[User, Depends(require_admin)],
    service: Annotated[SuppressionService, Depends(get_suppression_service_dep)],
    reason_code: SuppressionReasonCode | None = None,
) -> StreamingResponse:
    entries = await service.list_export_entries(actor=actor, reason_code=reason_code)
    buffer = io.StringIO(newline="")
    writer = csv.writer(buffer)
    writer.writerow(["email", "reason_code", "source", "first_suppressed_at", "expires_at"])
    for entry in entries:
        writer.writerow(
            [
                entry.email,
                service.to_reason_code(entry),
                service.to_source(entry),
                entry.created_at.isoformat(),
                entry.expires_at.isoformat() if entry.expires_at is not None else "",
            ]
        )
    buffer.seek(0)
    return StreamingResponse(
        iter([buffer.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="suppression-export.csv"'},
    )


@router.get("/{entry_id}/reveal", response_model=SuppressionRevealResponse)
@router.post("/{entry_id}/reveal", response_model=SuppressionRevealResponse)
async def reveal_suppression_email(
    entry_id: str,
    actor: Annotated[CurrentActor, Depends(get_current_actor)],
    _: Annotated[User, Depends(require_admin)],
    service: Annotated[SuppressionService, Depends(get_suppression_service_dep)],
) -> SuppressionRevealResponse:
    entry = await service.get_suppression_by_id(actor=actor, entry_id=entry_id)
    return SuppressionRevealResponse(id=entry.id, email=entry.email)


@router.get("/{email}", response_model=SuppressionEntryResponse)
async def get_suppression(
    email: str,
    actor: Annotated[CurrentActor, Depends(get_current_actor)],
    _: Annotated[User, Depends(require_admin)],
    service: Annotated[SuppressionService, Depends(get_suppression_service_dep)],
) -> SuppressionEntryResponse:
    entry = await service.get_suppression(actor=actor, email=email)
    return _to_response(entry, service)


@router.post("", response_model=SuppressionEntryResponse, status_code=status.HTTP_201_CREATED)
async def add_suppression(
    payload: SuppressionCreateRequest,
    request: Request,
    actor: Annotated[CurrentActor, Depends(get_current_actor)],
    _: Annotated[User, Depends(require_admin)],
    service: Annotated[SuppressionService, Depends(get_suppression_service_dep)],
) -> SuppressionEntryResponse:
    entry = await service.add_suppression(
        actor=actor,
        payload=payload,
        ip_address=_client_ip(request),
        user_agent=request.headers.get("user-agent"),
    )
    return _to_response(entry, service)


@router.delete("/{email}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_suppression(
    email: str,
    payload: SuppressionDeleteRequest,
    request: Request,
    actor: Annotated[CurrentActor, Depends(get_current_actor)],
    _: Annotated[User, Depends(require_admin)],
    service: Annotated[SuppressionService, Depends(get_suppression_service_dep)],
) -> None:
    await service.remove_suppression(
        actor=actor,
        email=email,
        justification=payload.justification,
        ip_address=_client_ip(request),
        user_agent=request.headers.get("user-agent"),
    )


@router.post("/bulk-import", response_model=SuppressionBulkImportResponse)
async def bulk_import_suppression(
    file: Annotated[UploadFile, File(...)],
    request: Request,
    actor: Annotated[CurrentActor, Depends(get_current_actor)],
    _: Annotated[User, Depends(require_admin)],
    service: Annotated[SuppressionService, Depends(get_suppression_service_dep)],
    reason_code: Annotated[SuppressionReasonCode, Form()] = "manual",
    source: Annotated[str, Form()] = "manual_csv_import",
    sync_to_ses: Annotated[bool, Form()] = True,
) -> SuppressionBulkImportResponse:
    content = await file.read()
    summary = await service.bulk_import_csv(
        actor=actor,
        csv_bytes=content,
        reason_code=reason_code,
        source=source,
        ip_address=_client_ip(request),
        user_agent=request.headers.get("user-agent"),
        sync_to_ses=sync_to_ses,
    )
    return SuppressionBulkImportResponse(
        imported_count=summary.imported_count,
        skipped_count=summary.skipped_count,
        invalid_count=summary.invalid_count,
        total_rows=summary.total_rows,
    )
