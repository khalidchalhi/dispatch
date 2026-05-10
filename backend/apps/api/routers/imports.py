from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Body, Depends, File, Form, Query, Request, UploadFile, status

from apps.api.deps import (
    get_current_actor,
    get_import_service_dep,
    get_suppression_service_dep,
    require_admin,
)
from apps.workers.celery_app import celery_app
from libs.core.auth.models import User
from libs.core.auth.schemas import CurrentActor
from libs.core.imports.schemas import ImportErrorRowResponse, ImportJobResponse
from libs.core.imports.service import ImportService
from libs.core.logging import get_logger
from libs.core.suppression.schemas import SuppressionBulkImportResponse
from libs.core.suppression.service import SuppressionService

logger = get_logger("api.imports")

router = APIRouter(tags=["imports"])


def _client_ip(request: Request) -> str | None:
    return request.client.host if request.client else None


@router.post("/imports", response_model=ImportJobResponse, status_code=status.HTTP_201_CREATED)
@router.post("/contacts/bulk-import", response_model=ImportJobResponse, status_code=status.HTTP_201_CREATED)
async def create_import_job(
    request: Request,
    file: Annotated[UploadFile, File(...)],
    source_label: Annotated[str | None, Form()] = None,
    target_list_id: Annotated[str | None, Form()] = None,
    *,
    actor: Annotated[CurrentActor, Depends(get_current_actor)],
    _: Annotated[User, Depends(require_admin)],
    service: Annotated[ImportService, Depends(get_import_service_dep)],
) -> ImportJobResponse:
    file_bytes = await file.read()
    job = await service.create_import_job(
        actor=actor,
        file_name=file.filename or "import.csv",
        file_bytes=file_bytes,
        source_label=source_label,
        target_list_id=target_list_id,
        ip_address=_client_ip(request),
        user_agent=request.headers.get("user-agent"),
    )

    try:
        celery_app.send_task("imports.run_import", kwargs={"job_id": job.id})
    except Exception as exc:
        logger.warning("imports.enqueue_failed", job_id=job.id, error=str(exc))

    return ImportJobResponse.from_model(job)


@router.get("/imports/{job_id}", response_model=ImportJobResponse)
@router.get("/imports/{job_id}/status", response_model=ImportJobResponse)
@router.get("/contacts/bulk-import/{job_id}", response_model=ImportJobResponse)
@router.get("/contacts/bulk-import/{job_id}/status", response_model=ImportJobResponse)
async def get_import_job_status(
    job_id: str,
    actor: Annotated[CurrentActor, Depends(get_current_actor)],
    _: Annotated[User, Depends(require_admin)],
    service: Annotated[ImportService, Depends(get_import_service_dep)],
) -> ImportJobResponse:
    return await service.get_import_job(actor=actor, job_id=job_id)


@router.get("/imports/{job_id}/errors", response_model=list[ImportErrorRowResponse])
@router.get("/contacts/bulk-import/{job_id}/errors", response_model=list[ImportErrorRowResponse])
async def get_import_job_errors(
    job_id: str,
    actor: Annotated[CurrentActor, Depends(get_current_actor)],
    _: Annotated[User, Depends(require_admin)],
    service: Annotated[ImportService, Depends(get_import_service_dep)],
    limit: Annotated[int, Query(ge=1, le=1000)] = 200,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[ImportErrorRowResponse]:
    rows = await service.get_import_job_error_rows(
        actor=actor,
        job_id=job_id,
        limit=limit,
        offset=offset,
    )
    return [ImportErrorRowResponse.from_model(row) for row in rows]


@router.post(
    "/contacts/bulk-unsubscribe",
    response_model=SuppressionBulkImportResponse,
    status_code=status.HTTP_200_OK,
)
async def bulk_unsubscribe_contacts(
    request: Request,
    csv_body: Annotated[bytes, Body(..., media_type="text/csv")],
    actor: Annotated[CurrentActor, Depends(get_current_actor)],
    _: Annotated[User, Depends(require_admin)],
    suppression_service: Annotated[SuppressionService, Depends(get_suppression_service_dep)],
) -> SuppressionBulkImportResponse:
    summary = await suppression_service.bulk_import_csv(
        actor=actor,
        csv_bytes=csv_body,
        reason_code="unsubscribe",
        source="contacts_bulk_unsubscribe",
        ip_address=_client_ip(request),
        user_agent=request.headers.get("user-agent"),
    )
    return SuppressionBulkImportResponse(
        imported_count=summary.imported_count,
        skipped_count=summary.skipped_count,
        invalid_count=summary.invalid_count,
        total_rows=summary.total_rows,
    )
