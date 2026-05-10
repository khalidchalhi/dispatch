from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query

from apps.api.deps import get_current_actor, get_domain_service_dep, require_admin
from libs.core.auth.models import User
from libs.core.auth.schemas import CurrentActor
from libs.core.domains.schemas import (
    DomainProvisioningAuditItemResponse,
    DomainProvisioningAuditListResponse,
    DomainProvisioningStepResponse,
)
from libs.core.domains.service import DomainService

router = APIRouter(prefix="/ops", tags=["ops"])


@router.get("/provisioning", response_model=DomainProvisioningAuditListResponse)
async def list_provisioning_audit(
    actor: Annotated[CurrentActor, Depends(get_current_actor)],
    _: Annotated[User, Depends(require_admin)],
    domain_service: Annotated[DomainService, Depends(get_domain_service_dep)],
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> DomainProvisioningAuditListResponse:
    entries = await domain_service.list_provisioning_audit(actor=actor, limit=limit)
    return DomainProvisioningAuditListResponse(
        items=[
            DomainProvisioningAuditItemResponse(
                id=entry.id,
                domain_id=entry.domain_id,
                domain_name=entry.domain_name,
                provider=entry.provider,
                status=entry.status,
                reason_code=entry.reason_code,
                started_at=entry.started_at,
                completed_at=entry.completed_at,
                steps=[
                    DomainProvisioningStepResponse(
                        name=step.name,
                        status=step.status,
                        at=step.at,
                        message=step.message,
                    )
                    for step in entry.steps
                ],
            )
            for entry in entries
        ]
    )
