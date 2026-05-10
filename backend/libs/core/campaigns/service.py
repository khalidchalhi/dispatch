from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from functools import lru_cache
from typing import Any

from itsdangerous import URLSafeTimedSerializer
from jinja2 import StrictUndefined
from jinja2.exceptions import SecurityError, TemplateError
from jinja2.sandbox import SandboxedEnvironment

from libs.core.auth.repository import AuthRepository
from libs.core.auth.schemas import CurrentActor
from libs.core.campaigns.models import Campaign, CampaignRun, Message
from libs.core.campaigns.repository import CampaignRepository
from libs.core.circuit_breaker.service import (
    CircuitBreakerService,
    get_circuit_breaker_service,
)
from libs.core.config import Settings, get_settings
from libs.core.db.pagination import CursorPage, OffsetPage, encode_cursor
from libs.core.db.session import get_session_factory
from libs.core.db.uow import UnitOfWork
from libs.core.errors import ConflictError, NotFoundError, PermissionDeniedError, ValidationError
from libs.core.logging import get_logger
from libs.core.segments.service import SegmentService, get_segment_service
from libs.core.throttle.token_bucket import DomainTokenBucket, get_domain_token_bucket
from libs.ses_client.client import SesClient, SesSendEmailRequest, get_ses_client
from libs.ses_client.errors import SesTerminalError

logger = get_logger("core.campaigns")

_LAUNCHABLE_CAMPAIGN_STATUSES = {"draft", "scheduled"}
_RESUMABLE_CAMPAIGN_STATUS = "paused"
_PAUSABLE_CAMPAIGN_STATUS = "running"
_SEND_BATCH_SIZE = 500

_SPAM_TRAP_SEED_DOMAINS = {
    "example.com",
    "mailinator.com",
    "10minutemail.com",
    "guerrillamail.com",
    "tempmail.com",
}
_SPAM_TRAP_LOCAL_FRAGMENTS = (
    "spamtrap",
    "honeypot",
    "seed",
    "abuse",
    "trap",
)


class _LockedDownSandbox(SandboxedEnvironment):
    def is_safe_attribute(self, obj: object, attr: str, value: object) -> bool:  # noqa: ANN001
        if attr.startswith("_"):
            return False
        return super().is_safe_attribute(obj, attr, value)

    def is_safe_callable(self, obj: object) -> bool:  # noqa: ANN001
        return False


@dataclass(slots=True)
class CampaignLaunchResult:
    campaign: Campaign
    campaign_run: CampaignRun
    snapshot_rows: int
    created_messages: int
    enqueued_messages: int
    already_launched: bool


@dataclass(slots=True)
class CampaignStateResult:
    campaign: Campaign
    enqueued_messages: int = 0
    cancelled_queued_messages: int = 0


@dataclass(slots=True)
class MessageSendResult:
    message_id: str
    status: str
    ses_message_id: str | None = None
    error_code: str | None = None
    error_message: str | None = None
    retry_after_seconds: int | None = None
    domain_id: str | None = None
    domain_name: str | None = None


@dataclass(slots=True, frozen=True)
class SendMessageDispatchContext:
    message_id: str
    status: str
    error_code: str | None
    domain_id: str
    domain_name: str
    domain_rate_limit_per_hour: int


@dataclass(slots=True, frozen=True)
class CampaignPreflightCheck:
    id: str
    label: str
    severity: str
    detail: str


@dataclass(slots=True, frozen=True)
class CampaignPreflightResult:
    campaign_id: str
    checks: list[CampaignPreflightCheck]
    generated_at: datetime


class CampaignService:
    def __init__(
        self,
        settings: Settings,
        *,
        ses_client: SesClient | None = None,
        segment_service: SegmentService | None = None,
        token_bucket: DomainTokenBucket | None = None,
        circuit_breaker_service: CircuitBreakerService | None = None,
    ) -> None:
        self._settings = settings
        self._session_factory = get_session_factory()
        self._ses_client = ses_client or get_ses_client()
        self._segment_service = segment_service or get_segment_service()
        self._token_bucket = token_bucket or get_domain_token_bucket()
        self._circuit_breaker_service = circuit_breaker_service or get_circuit_breaker_service()
        self._unsubscribe_serializer = URLSafeTimedSerializer(
            settings.secret_key,
            salt="dispatch-public-unsubscribe",
        )
        self._renderer = _LockedDownSandbox(autoescape=False, undefined=StrictUndefined)
        self._renderer.globals.clear()
        self._renderer.filters.clear()
        self._renderer.tests.clear()

    async def list_campaigns(
        self,
        *,
        actor: CurrentActor,
        limit: int,
        offset: int,
        status: str | None = None,
    ) -> OffsetPage[Campaign]:
        self._require_admin(actor)
        async with self._session_factory() as session:
            repo = CampaignRepository(session)
            items = await repo.list_campaigns(limit=limit, offset=offset, status=status)
            total = await repo.count_campaigns(status=status)
        return OffsetPage(items=items, total=total, limit=limit, offset=offset)

    async def create_campaign(
        self,
        *,
        actor: CurrentActor,
        payload: Any,
        ip_address: str | None,
        user_agent: str | None,
    ) -> Campaign:
        self._require_admin(actor)
        async with UnitOfWork(self._session_factory) as uow:
            repo = CampaignRepository(uow.require_session())
            sender_profile = await repo.get_sender_profile_by_id(payload.sender_profile_id)
            if sender_profile is None:
                raise NotFoundError("Sender profile not found")

            template_version_id = await self._resolve_template_version_id(
                repo=repo,
                template_version_id=payload.template_version_id,
                template_id=payload.template_id,
                template_version=payload.template_version,
            )
            segment_id, list_id = self._resolve_audience_ids(
                segment_id=payload.segment_id,
                list_id=payload.list_id,
                audience_type=payload.audience_type,
                audience_id=payload.audience_id,
            )
            schedule_type, scheduled_at = self._resolve_schedule(
                schedule_type=payload.schedule_type,
                scheduled_at=payload.scheduled_at,
            )

            campaign = Campaign(
                name=payload.name.strip(),
                campaign_type=payload.campaign_type.strip(),
                sender_profile_id=sender_profile.id,
                template_version_id=template_version_id,
                segment_id=segment_id,
                list_id=list_id,
                schedule_type=schedule_type,
                scheduled_at=scheduled_at,
                timezone=payload.timezone,
                send_rate_per_hour=payload.send_rate_per_hour,
                status="scheduled" if schedule_type == "scheduled" else "draft",
                tracking_opens=payload.tracking_opens,
                tracking_clicks=payload.tracking_clicks,
                created_by=actor.user.id,
            )
            uow.require_session().add(campaign)
            await uow.require_session().flush()

            await AuthRepository(uow.require_session()).write_audit_log(
                actor_type=actor.actor_type,
                actor_id=actor.user.id,
                action="campaign.create",
                resource_type="campaign",
                resource_id=campaign.id,
                after_state={
                    "status": campaign.status,
                    "schedule_type": schedule_type,
                    "segment_id": segment_id,
                    "list_id": list_id,
                },
                ip_address=ip_address,
                user_agent=user_agent,
            )
            return campaign

    async def get_campaign(self, *, actor: CurrentActor, campaign_id: str) -> Campaign:
        self._require_admin(actor)
        async with self._session_factory() as session:
            repo = CampaignRepository(session)
            campaign = await repo.get_campaign_by_id(campaign_id)
            if campaign is None:
                raise NotFoundError("Campaign not found")
            return campaign

    async def update_campaign(
        self,
        *,
        actor: CurrentActor,
        campaign_id: str,
        payload: Any,
        ip_address: str | None,
        user_agent: str | None,
    ) -> Campaign:
        self._require_admin(actor)
        async with UnitOfWork(self._session_factory) as uow:
            repo = CampaignRepository(uow.require_session())
            campaign = await repo.get_campaign_by_id(campaign_id)
            if campaign is None:
                raise NotFoundError("Campaign not found")
            if campaign.status in {"running", "completed", "cancelled", "failed"}:
                raise ConflictError("Campaign cannot be edited in its current status")

            values: dict[str, object] = {}
            changed = payload.model_fields_set

            if "name" in changed and payload.name is not None:
                values["name"] = payload.name.strip()
            if "campaign_type" in changed and payload.campaign_type is not None:
                values["campaign_type"] = payload.campaign_type.strip()
            if "sender_profile_id" in changed and payload.sender_profile_id is not None:
                sender_profile = await repo.get_sender_profile_by_id(payload.sender_profile_id)
                if sender_profile is None:
                    raise NotFoundError("Sender profile not found")
                values["sender_profile_id"] = sender_profile.id

            should_update_template = (
                "template_version_id" in changed
                or "template_id" in changed
                or "template_version" in changed
            )
            if should_update_template:
                values["template_version_id"] = await self._resolve_template_version_id(
                    repo=repo,
                    template_version_id=payload.template_version_id,
                    template_id=payload.template_id,
                    template_version=payload.template_version,
                    fallback_template_version_id=campaign.template_version_id,
                )

            should_update_audience = (
                "segment_id" in changed
                or "list_id" in changed
                or "audience_type" in changed
                or "audience_id" in changed
            )
            if should_update_audience:
                segment_id, list_id = self._resolve_audience_ids(
                    segment_id=(
                        payload.segment_id if "segment_id" in changed else campaign.segment_id
                    ),
                    list_id=payload.list_id if "list_id" in changed else campaign.list_id,
                    audience_type=payload.audience_type if "audience_type" in changed else None,
                    audience_id=payload.audience_id if "audience_id" in changed else None,
                )
                values["segment_id"] = segment_id
                values["list_id"] = list_id

            if "timezone" in changed and payload.timezone is not None:
                values["timezone"] = payload.timezone
            if "send_rate_per_hour" in changed and payload.send_rate_per_hour is not None:
                values["send_rate_per_hour"] = payload.send_rate_per_hour
            if "tracking_opens" in changed and payload.tracking_opens is not None:
                values["tracking_opens"] = payload.tracking_opens
            if "tracking_clicks" in changed and payload.tracking_clicks is not None:
                values["tracking_clicks"] = payload.tracking_clicks

            should_update_schedule = "schedule_type" in changed or "scheduled_at" in changed
            if should_update_schedule:
                schedule_type, scheduled_at = self._resolve_schedule(
                    schedule_type=payload.schedule_type or campaign.schedule_type,
                    scheduled_at=payload.scheduled_at,
                )
                values["schedule_type"] = schedule_type
                values["scheduled_at"] = scheduled_at
                if campaign.status == "draft" and schedule_type == "scheduled":
                    values["status"] = "scheduled"
                if campaign.status == "scheduled" and schedule_type == "immediate":
                    values["status"] = "draft"

            if values:
                await repo.update_campaign(campaign_id=campaign.id, values=values)

            refreshed = await repo.get_campaign_by_id(campaign.id)
            if refreshed is None:
                raise NotFoundError("Campaign not found")

            await AuthRepository(uow.require_session()).write_audit_log(
                actor_type=actor.actor_type,
                actor_id=actor.user.id,
                action="campaign.update",
                resource_type="campaign",
                resource_id=campaign.id,
                after_state={"changed_fields": sorted(values.keys())},
                ip_address=ip_address,
                user_agent=user_agent,
            )
            return refreshed

    async def get_campaign_preflight(
        self,
        *,
        actor: CurrentActor,
        campaign_id: str,
    ) -> CampaignPreflightResult:
        self._require_admin(actor)
        async with self._session_factory() as session:
            repo = CampaignRepository(session)
            campaign = await repo.get_campaign_by_id(campaign_id)
            if campaign is None:
                raise NotFoundError("Campaign not found")

            checks: list[CampaignPreflightCheck] = []

            sender_profile = await repo.get_sender_profile_by_id(campaign.sender_profile_id)
            if sender_profile is None:
                checks.append(
                    CampaignPreflightCheck(
                        id="sender_profile",
                        label="Sender profile",
                        severity="critical",
                        detail="Sender profile is missing",
                    )
                )
            elif not sender_profile.is_active:
                checks.append(
                    CampaignPreflightCheck(
                        id="sender_profile",
                        label="Sender profile",
                        severity="critical",
                        detail="Sender profile is paused",
                    )
                )
            else:
                checks.append(
                    CampaignPreflightCheck(
                        id="sender_profile",
                        label="Sender profile",
                        severity="ok",
                        detail="Sender profile is active",
                    )
                )

            domain = (
                await repo.get_domain_by_id(sender_profile.domain_id)
                if sender_profile is not None
                else None
            )
            if domain is None:
                checks.append(
                    CampaignPreflightCheck(
                        id="domain",
                        label="Domain health",
                        severity="critical",
                        detail="Domain is missing",
                    )
                )
            elif domain.verification_status != "verified":
                checks.append(
                    CampaignPreflightCheck(
                        id="domain",
                        label="Domain health",
                        severity="critical",
                        detail="Domain is not verified",
                    )
                )
            elif domain.reputation_status in {"burnt", "retired"}:
                checks.append(
                    CampaignPreflightCheck(
                        id="domain",
                        label="Domain health",
                        severity="critical",
                        detail=f"Domain reputation is {domain.reputation_status}",
                    )
                )
            elif domain.reputation_status == "cooling":
                checks.append(
                    CampaignPreflightCheck(
                        id="domain",
                        label="Domain health",
                        severity="warning",
                        detail="Domain is in cooling state",
                    )
                )
            else:
                checks.append(
                    CampaignPreflightCheck(
                        id="domain",
                        label="Domain health",
                        severity="ok",
                        detail="Domain is sendable",
                    )
                )

            template_version = await repo.get_template_version_by_id(campaign.template_version_id)
            checks.append(
                CampaignPreflightCheck(
                    id="template",
                    label="Template version",
                    severity="ok" if template_version is not None else "critical",
                    detail=(
                        "Template version exists"
                        if template_version is not None
                        else "Template version is missing"
                    ),
                )
            )

            if campaign.segment_id is None and campaign.list_id is None:
                checks.append(
                    CampaignPreflightCheck(
                        id="audience",
                        label="Audience",
                        severity="critical",
                        detail="Campaign has no audience configured",
                    )
                )
            else:
                checks.append(
                    CampaignPreflightCheck(
                        id="audience",
                        label="Audience",
                        severity="ok",
                        detail=(
                            "Segment-based audience configured"
                            if campaign.segment_id is not None
                            else "List-based audience configured"
                        ),
                    )
                )

            if campaign.schedule_type == "scheduled" and campaign.scheduled_at is None:
                checks.append(
                    CampaignPreflightCheck(
                        id="schedule",
                        label="Schedule",
                        severity="critical",
                        detail="Scheduled campaign is missing scheduled_at",
                    )
                )
            else:
                checks.append(
                    CampaignPreflightCheck(
                        id="schedule",
                        label="Schedule",
                        severity="ok",
                        detail="Schedule configuration is valid",
                    )
                )

            if campaign.segment_id is not None:
                try:
                    preview = await self._segment_service.preview_segment(
                        actor=actor,
                        segment_id=campaign.segment_id,
                        sample_limit=1,
                    )
                    checks.append(
                        CampaignPreflightCheck(
                            id="segment_size",
                            label="Segment size",
                            severity="warning" if preview.total_count == 0 else "ok",
                            detail=f"{preview.total_count} eligible contact(s) in preview",
                        )
                    )
                except Exception:
                    checks.append(
                        CampaignPreflightCheck(
                            id="segment_size",
                            label="Segment size",
                            severity="warning",
                            detail="Segment preview unavailable",
                        )
                    )

        return CampaignPreflightResult(
            campaign_id=campaign_id,
            checks=checks,
            generated_at=datetime.now(UTC),
        )

    async def list_campaign_messages(
        self,
        *,
        actor: CurrentActor,
        campaign_id: str,
        limit: int,
        cursor: str | None,
        status: str | None = None,
    ) -> CursorPage[Message]:
        self._require_admin(actor)
        async with self._session_factory() as session:
            repo = CampaignRepository(session)
            campaign = await repo.get_campaign_by_id(campaign_id)
            if campaign is None:
                raise NotFoundError("Campaign not found")
            rows = await repo.list_messages_for_campaign(
                campaign_id=campaign_id,
                limit=limit,
                cursor=cursor,
                status=status,
            )

        has_more = len(rows) > limit
        page = rows[:limit]
        next_cursor = encode_cursor(page[-1].created_at, page[-1].id) if has_more and page else None
        return CursorPage(items=page, next_cursor=next_cursor)

    async def requeue_campaign_message(
        self,
        *,
        actor: CurrentActor,
        campaign_id: str,
        message_id: str,
        ip_address: str | None,
        user_agent: str | None,
    ) -> Message:
        self._require_admin(actor)
        queued_message_id: str | None = None
        domain_id: str | None = None
        domain_name: str | None = None

        async with UnitOfWork(self._session_factory) as uow:
            repo = CampaignRepository(uow.require_session())
            campaign = await repo.get_campaign_by_id(campaign_id)
            if campaign is None:
                raise NotFoundError("Campaign not found")

            source_message = await repo.get_message_by_id(message_id)
            if source_message is None or source_message.campaign_id != campaign_id:
                raise NotFoundError("Message not found")
            if source_message.status not in {"failed", "paused"}:
                raise ConflictError("Only failed or paused messages can be re-queued")

            requeued = Message(
                campaign_id=source_message.campaign_id,
                send_batch_id=source_message.send_batch_id,
                contact_id=source_message.contact_id,
                sender_profile_id=source_message.sender_profile_id,
                domain_id=source_message.domain_id,
                to_email=source_message.to_email,
                from_email=source_message.from_email,
                subject=source_message.subject,
                status="queued",
                headers={
                    **dict(source_message.headers or {}),
                    "requeued_from_message_id": source_message.id,
                },
            )
            uow.require_session().add(requeued)
            await uow.require_session().flush()
            queued_message_id = requeued.id
            domain_id = requeued.domain_id

            domain = await repo.get_domain_by_id(requeued.domain_id)
            domain_name = domain.name if domain is not None else None

            await AuthRepository(uow.require_session()).write_audit_log(
                actor_type=actor.actor_type,
                actor_id=actor.user.id,
                action="campaign.message.requeue",
                resource_type="message",
                resource_id=requeued.id,
                after_state={
                    "campaign_id": campaign_id,
                    "source_message_id": source_message.id,
                    "status": "queued",
                },
                ip_address=ip_address,
                user_agent=user_agent,
            )

        if queued_message_id is None:
            raise RuntimeError("Failed to create re-queued message")

        if domain_id and domain_name:
            try:
                from apps.workers.celery_app import celery_app

                celery_app.send_task(
                    "send.send_message",
                    kwargs={
                        "message_id": queued_message_id,
                        "domain_id": domain_id,
                        "domain_name": domain_name,
                    },
                )
            except Exception as exc:  # pragma: no cover - defensive logging path
                logger.warning(
                    "campaigns.requeue_enqueue_failed",
                    campaign_id=campaign_id,
                    message_id=queued_message_id,
                    error=str(exc),
                )

        async with self._session_factory() as session:
            repo = CampaignRepository(session)
            refreshed = await repo.get_message_by_id(queued_message_id)
            if refreshed is None:
                raise NotFoundError("Message not found")
            return refreshed

    async def launch_campaign(
        self,
        *,
        actor: CurrentActor,
        campaign_id: str,
        ip_address: str | None,
        user_agent: str | None,
    ) -> CampaignLaunchResult:
        self._require_admin(actor)

        campaign, run, already_launched = await self._ensure_campaign_run(
            actor=actor,
            campaign_id=campaign_id,
            ip_address=ip_address,
            user_agent=user_agent,
        )

        if campaign.segment_id is None:
            raise ConflictError("Campaign requires a segment before launch")

        freeze_result = await self._segment_service.freeze_segment(
            segment_id=campaign.segment_id,
            campaign_run_id=run.id,
        )

        created_messages = await self._materialize_run_messages(
            campaign_id=campaign.id,
            campaign_run_id=run.id,
        )
        enqueued_messages = await self.enqueue_queued_messages(campaign_run_id=run.id)

        refreshed_campaign = await self._refresh_campaign(campaign.id)
        refreshed_run = await self._refresh_run(run.id)

        return CampaignLaunchResult(
            campaign=refreshed_campaign,
            campaign_run=refreshed_run,
            snapshot_rows=freeze_result.snapshot_rows,
            created_messages=created_messages,
            enqueued_messages=enqueued_messages,
            already_launched=already_launched,
        )

    async def pause_campaign(
        self,
        *,
        actor: CurrentActor,
        campaign_id: str,
        ip_address: str | None,
        user_agent: str | None,
    ) -> CampaignStateResult:
        self._require_admin(actor)
        async with UnitOfWork(self._session_factory) as uow:
            repo = CampaignRepository(uow.require_session())
            campaign = await repo.get_campaign_by_id(campaign_id)
            if campaign is None:
                raise NotFoundError("Campaign not found")
            if campaign.status != _PAUSABLE_CAMPAIGN_STATUS:
                raise ConflictError("Only running campaigns can be paused")

            await repo.update_campaign(campaign_id=campaign.id, values={"status": "paused"})
            latest_run = await repo.get_latest_campaign_run_for_campaign(campaign.id)
            if latest_run is not None and latest_run.status == "running":
                await repo.update_campaign_run(
                    campaign_run_id=latest_run.id,
                    values={"status": "paused"},
                )

            await AuthRepository(uow.require_session()).write_audit_log(
                actor_type=actor.actor_type,
                actor_id=actor.user.id,
                action="campaign.pause",
                resource_type="campaign",
                resource_id=campaign.id,
                after_state={"status": "paused"},
                ip_address=ip_address,
                user_agent=user_agent,
            )

        refreshed = await self._refresh_campaign(campaign_id)
        return CampaignStateResult(campaign=refreshed)

    async def resume_campaign(
        self,
        *,
        actor: CurrentActor,
        campaign_id: str,
        ip_address: str | None,
        user_agent: str | None,
    ) -> CampaignStateResult:
        self._require_admin(actor)
        run_id: str | None = None
        async with UnitOfWork(self._session_factory) as uow:
            repo = CampaignRepository(uow.require_session())
            campaign = await repo.get_campaign_by_id(campaign_id)
            if campaign is None:
                raise NotFoundError("Campaign not found")
            if campaign.status != _RESUMABLE_CAMPAIGN_STATUS:
                raise ConflictError("Only paused campaigns can be resumed")

            await repo.update_campaign(campaign_id=campaign.id, values={"status": "running"})
            latest_run = await repo.get_latest_campaign_run_for_campaign(campaign.id)
            if latest_run is not None:
                run_id = latest_run.id
                if latest_run.status in {"paused", "running"}:
                    await repo.update_campaign_run(
                        campaign_run_id=latest_run.id,
                        values={"status": "running"},
                    )

            await AuthRepository(uow.require_session()).write_audit_log(
                actor_type=actor.actor_type,
                actor_id=actor.user.id,
                action="campaign.resume",
                resource_type="campaign",
                resource_id=campaign.id,
                after_state={"status": "running"},
                ip_address=ip_address,
                user_agent=user_agent,
            )

        enqueued_messages = 0
        if run_id is not None:
            enqueued_messages = await self.enqueue_queued_messages(campaign_run_id=run_id)

        refreshed = await self._refresh_campaign(campaign_id)
        return CampaignStateResult(
            campaign=refreshed,
            enqueued_messages=enqueued_messages,
        )

    async def cancel_campaign(
        self,
        *,
        actor: CurrentActor,
        campaign_id: str,
        ip_address: str | None,
        user_agent: str | None,
    ) -> CampaignStateResult:
        self._require_admin(actor)
        cancelled_queued_messages = 0
        async with UnitOfWork(self._session_factory) as uow:
            repo = CampaignRepository(uow.require_session())
            campaign = await repo.get_campaign_by_id(campaign_id)
            if campaign is None:
                raise NotFoundError("Campaign not found")
            if campaign.status in {"completed", "cancelled", "failed"}:
                raise ConflictError("Campaign is already terminal")

            now = datetime.now(UTC)
            await repo.update_campaign(
                campaign_id=campaign.id,
                values={"status": "cancelled", "completed_at": now},
            )

            latest_run = await repo.get_latest_campaign_run_for_campaign(campaign.id)
            if latest_run is not None and latest_run.status not in {
                "completed",
                "cancelled",
                "failed",
            }:
                await repo.update_campaign_run(
                    campaign_run_id=latest_run.id,
                    values={"status": "cancelled", "completed_at": now},
                )

            cancelled_queued_messages = await repo.cancel_queued_messages_for_campaign(campaign.id)

            await AuthRepository(uow.require_session()).write_audit_log(
                actor_type=actor.actor_type,
                actor_id=actor.user.id,
                action="campaign.cancel",
                resource_type="campaign",
                resource_id=campaign.id,
                after_state={
                    "status": "cancelled",
                    "cancelled_queued_messages": cancelled_queued_messages,
                },
                ip_address=ip_address,
                user_agent=user_agent,
            )

        refreshed = await self._refresh_campaign(campaign_id)
        return CampaignStateResult(
            campaign=refreshed,
            cancelled_queued_messages=cancelled_queued_messages,
        )

    async def enqueue_queued_messages(self, *, campaign_run_id: str) -> int:
        async with self._session_factory() as session:
            repo = CampaignRepository(session)
            targets = await repo.list_queued_message_dispatch_targets_for_run(campaign_run_id)

        if not targets:
            return 0

        from apps.workers.celery_app import celery_app

        queued_count = 0
        for target in targets:
            try:
                celery_app.send_task(
                    "send.send_message",
                    kwargs={
                        "message_id": target.message_id,
                        "domain_id": target.domain_id,
                        "domain_name": target.domain_name,
                    },
                )
            except Exception as exc:  # pragma: no cover - defensive logging path
                logger.warning(
                    "campaigns.enqueue_message_failed",
                    campaign_run_id=campaign_run_id,
                    message_id=target.message_id,
                    error=str(exc),
                )
                continue
            queued_count += 1

        async with UnitOfWork(self._session_factory) as uow:
            await CampaignRepository(uow.require_session()).mark_batches_enqueued(campaign_run_id)

        return queued_count

    async def send_queued_message(self, *, message_id: str) -> MessageSendResult:
        async with UnitOfWork(self._session_factory) as uow:
            repo = CampaignRepository(uow.require_session())
            message = await repo.get_message_by_id(message_id)
            if message is None:
                raise NotFoundError("Message not found")

            if message.status not in {"queued", "paused"}:
                return MessageSendResult(
                    message_id=message.id,
                    status=message.status,
                    ses_message_id=message.ses_message_id,
                    error_code=message.error_code,
                    error_message=message.error_message,
                )
            if message.status == "paused" and message.error_code != "circuit_open":
                return MessageSendResult(
                    message_id=message.id,
                    status=message.status,
                    ses_message_id=message.ses_message_id,
                    error_code=message.error_code,
                    error_message=message.error_message,
                )

            campaign = await self._get_campaign_for_message(repo=repo, message=message)
            if campaign is not None and campaign.status != "running":
                return MessageSendResult(
                    message_id=message.id,
                    status=message.status,
                    error_code="campaign_not_running",
                    error_message="Campaign is not running",
                )

            domain = await repo.get_domain_by_id(message.domain_id)
            if domain is None:
                self._fail_message(
                    message,
                    error_code="missing_domain",
                    error_message="Domain not found for message",
                )
                return self._result_from_message(message)

            sender_profile = await repo.get_sender_profile_by_id(message.sender_profile_id)
            if sender_profile is None:
                self._fail_message(
                    message,
                    error_code="missing_sender_profile",
                    error_message="Sender profile not found for message",
                )
                return self._result_from_message(message)

            breaker_scopes: list[tuple[str, str]] = [
                ("domain", domain.id),
                ("sender_profile", sender_profile.id),
                ("account", self._circuit_breaker_service.account_scope_id()),
            ]
            if sender_profile.ip_pool_id is not None:
                breaker_scopes.append(("ip_pool", sender_profile.ip_pool_id))

            open_scope = await self._circuit_breaker_service.first_open_scope(scopes=breaker_scopes)
            if open_scope is not None:
                scope_type, scope_id = open_scope
                message.status = "paused"
                message.error_code = "circuit_open"
                message.error_message = (
                    f"Circuit breaker open for {scope_type}:{scope_id}; retry after cooldown"
                )
                message.sent_at = None
                return MessageSendResult(
                    message_id=message.id,
                    status="paused",
                    error_code="circuit_open",
                    error_message=message.error_message,
                    retry_after_seconds=self._circuit_breaker_service.recheck_delay_seconds,
                    domain_id=domain.id,
                    domain_name=domain.name,
                )

            if message.status == "paused":
                message.status = "queued"
                message.error_code = None
                message.error_message = None

            if domain.warmup_stage == "warming" and domain.daily_send_limit > 0:
                daily_decision = await self._token_bucket.try_take_daily(
                    domain_id=domain.id,
                    daily_limit=domain.daily_send_limit,
                )
                if not daily_decision.allowed:
                    now = datetime.now(UTC)
                    seconds_until_midnight = (
                        (23 - now.hour) * 3600
                        + (59 - now.minute) * 60
                        + (60 - now.second)
                    )
                    return MessageSendResult(
                        message_id=message.id,
                        status="queued",
                        error_code="daily_cap_reached",
                        error_message="Domain daily warmup budget exhausted; retry tomorrow",
                        retry_after_seconds=max(seconds_until_midnight, 3600),
                        domain_id=domain.id,
                        domain_name=domain.name,
                    )

            claimed = await repo.claim_message_for_sending(message.id)
            if not claimed:
                refreshed = await repo.get_message_by_id(message.id)
                if refreshed is None:
                    raise NotFoundError("Message not found")
                return MessageSendResult(
                    message_id=refreshed.id,
                    status=refreshed.status,
                    ses_message_id=refreshed.ses_message_id,
                    error_code=refreshed.error_code,
                    error_message=refreshed.error_message,
                )

            message = await repo.get_message_by_id(message.id)
            if message is None:
                raise NotFoundError("Message not found")

            if message.contact_id is None:
                self._fail_message(
                    message,
                    error_code="missing_contact",
                    error_message="Message is missing contact_id",
                )
                return self._result_from_message(message)

            subscription = await repo.get_subscription_status_for_contact(message.contact_id)
            if subscription is not None and subscription.status == "unsubscribed":
                self._fail_message(
                    message,
                    error_code="contact_unsubscribed",
                    error_message="Contact is unsubscribed",
                )
                return self._result_from_message(message)

            local_suppression = await repo.find_active_suppression_by_email(message.to_email)
            if local_suppression is not None:
                self._fail_message(
                    message,
                    error_code="suppressed_local",
                    error_message="Recipient is present in suppression_entries",
                )
                return self._result_from_message(message)

            remote_suppression = await self._ses_client.get_suppressed_destination(
                email=message.to_email,
            )
            if remote_suppression is not None:
                self._fail_message(
                    message,
                    error_code="suppressed_remote",
                    error_message="Recipient exists in SES account-level suppression",
                )
                return self._result_from_message(message)

            if self._is_spam_trap_candidate(message.to_email):
                self._fail_message(
                    message,
                    error_code="spam_trap_heuristic",
                    error_message="Spam trap heuristic blocked send",
                )
                return self._result_from_message(message)

            ml_score = self._ml_spam_score_stub(message)
            if ml_score > 0.2:
                self._fail_message(
                    message,
                    error_code="ml_spam_gate",
                    error_message="ML spam scorer blocked send",
                )
                return self._result_from_message(message)

            if campaign is None:
                self._fail_message(
                    message,
                    error_code="missing_campaign",
                    error_message="Message campaign relation is missing",
                )
                return self._result_from_message(message)

            template_version = await repo.get_template_version_by_id(campaign.template_version_id)
            if template_version is None:
                self._fail_message(
                    message,
                    error_code="missing_template_version",
                    error_message="Template version not found",
                )
                return self._result_from_message(message)

            contact = await repo.get_contact_by_id(message.contact_id)
            if contact is None:
                self._fail_message(
                    message,
                    error_code="missing_contact",
                    error_message="Contact not found",
                )
                return self._result_from_message(message)

            snapshot = await repo.get_segment_snapshot_for_message(message.id)
            contact_payload = self._build_contact_payload(contact=contact, snapshot=snapshot)

            try:
                rendered_subject = self._render_template_string(
                    template_version.subject,
                    contact_payload,
                )
                rendered_body_text = self._render_template_string(
                    template_version.body_text,
                    contact_payload,
                )
                rendered_body_html = (
                    self._render_template_string(template_version.body_html, contact_payload)
                    if template_version.body_html is not None
                    else None
                )
            except ValidationError as exc:
                self._fail_message(
                    message,
                    error_code="render_failed",
                    error_message=exc.message,
                )
                return self._result_from_message(message)

            try:
                list_unsubscribe_headers = self._build_list_unsubscribe_headers(
                    contact_id=contact.id
                )
                send_result = await self._ses_client.send_email(
                    SesSendEmailRequest(
                        from_email=message.from_email,
                        to_email=message.to_email,
                        subject=rendered_subject,
                        body_text=rendered_body_text,
                        body_html=rendered_body_html,
                        tags=[
                            ("message_id", message.id),
                            ("campaign_id", campaign.id),
                        ],
                        headers=list_unsubscribe_headers,
                    )
                )
            except SesTerminalError as exc:
                self._fail_message(
                    message,
                    error_code=exc.code,
                    error_message=exc.message,
                )
                return self._result_from_message(message)

            message.subject = rendered_subject
            message.ses_message_id = send_result.message_id
            message.status = "sent"
            message.sent_at = datetime.now(UTC)
            message.error_code = None
            message.error_message = None
            message.ml_spam_score = ml_score
            message.headers = {
                **dict(message.headers or {}),
                "gate7_ml_score": ml_score,
                "list_unsubscribe_headers": {
                    key: value for key, value in list_unsubscribe_headers
                },
            }

            run = await repo.get_campaign_run_by_message_id(message.id)
            if run is not None:
                await repo.increment_campaign_run_sent_count(run.id)
            await repo.increment_campaign_total_sent(campaign.id)

            return self._result_from_message(message)

    async def get_send_message_dispatch_context(
        self,
        *,
        message_id: str,
    ) -> SendMessageDispatchContext | None:
        async with self._session_factory() as session:
            repo = CampaignRepository(session)
            context = await repo.get_message_dispatch_context(message_id)
            if context is None:
                return None
            return SendMessageDispatchContext(
                message_id=context.message_id,
                status=context.status,
                error_code=context.error_code,
                domain_id=context.domain_id,
                domain_name=context.domain_name,
                domain_rate_limit_per_hour=self._resolve_domain_rate_limit_per_hour(
                    context.domain_rate_limit_per_hour
                ),
            )

    async def _resolve_template_version_id(
        self,
        *,
        repo: CampaignRepository,
        template_version_id: str | None,
        template_id: str | None,
        template_version: int | None,
        fallback_template_version_id: str | None = None,
    ) -> str:
        if template_version_id:
            version = await repo.get_template_version_by_id(template_version_id)
            if version is None:
                raise NotFoundError("Template version not found")
            return version.id

        if template_id and template_version is not None:
            version = await repo.get_template_version_by_template_and_number(
                template_id=template_id,
                version_number=template_version,
            )
            if version is None:
                raise NotFoundError("Template version not found")
            return version.id

        if fallback_template_version_id is not None:
            return fallback_template_version_id

        raise ValidationError(
            "Provide template_version_id or template_id with template_version"
        )

    @staticmethod
    def _resolve_audience_ids(
        *,
        segment_id: str | None,
        list_id: str | None,
        audience_type: str | None,
        audience_id: str | None,
    ) -> tuple[str | None, str | None]:
        resolved_segment_id = segment_id
        resolved_list_id = list_id

        if audience_type is not None or audience_id is not None:
            if audience_type not in {"segment", "list"}:
                raise ValidationError("audience_type must be either 'segment' or 'list'")
            if not audience_id:
                raise ValidationError("audience_id is required when audience_type is set")
            if audience_type == "segment":
                resolved_segment_id = audience_id
                resolved_list_id = None
            else:
                resolved_segment_id = None
                resolved_list_id = audience_id

        if resolved_segment_id and resolved_list_id:
            raise ValidationError("Campaign audience must reference either a segment or a list")
        if not resolved_segment_id and not resolved_list_id:
            raise ValidationError("Campaign audience is required")
        return resolved_segment_id, resolved_list_id

    @staticmethod
    def _resolve_schedule(
        *,
        schedule_type: str,
        scheduled_at: datetime | None,
    ) -> tuple[str, datetime | None]:
        if schedule_type not in {"immediate", "scheduled"}:
            raise ValidationError("schedule_type must be immediate or scheduled")
        if schedule_type == "scheduled" and scheduled_at is None:
            raise ValidationError("scheduled_at is required when schedule_type is scheduled")
        if schedule_type == "immediate":
            return "immediate", None
        return "scheduled", scheduled_at

    async def _ensure_campaign_run(
        self,
        *,
        actor: CurrentActor,
        campaign_id: str,
        ip_address: str | None,
        user_agent: str | None,
    ) -> tuple[Campaign, CampaignRun, bool]:
        async with UnitOfWork(self._session_factory) as uow:
            repo = CampaignRepository(uow.require_session())
            campaign = await repo.get_campaign_by_id(campaign_id)
            if campaign is None:
                raise NotFoundError("Campaign not found")

            latest_run = await repo.get_latest_campaign_run_for_campaign(campaign.id)
            if campaign.status in {"running", "paused"}:
                if latest_run is None:
                    raise ConflictError("Campaign has no run to continue")
                return campaign, latest_run, True

            if campaign.status not in _LAUNCHABLE_CAMPAIGN_STATUSES:
                raise ConflictError(f"Campaign cannot be launched from status {campaign.status}")

            sender_profile = await repo.get_sender_profile_by_id(campaign.sender_profile_id)
            if sender_profile is None:
                raise NotFoundError("Sender profile not found")
            if not sender_profile.is_active:
                raise ConflictError("Sender profile is paused")

            domain = await repo.get_domain_by_id(sender_profile.domain_id)
            if domain is None:
                raise NotFoundError("Domain not found")
            if domain.verification_status != "verified":
                raise ConflictError("Campaign domain is not verified")
            if domain.reputation_status in {"burnt", "retired"}:
                raise ConflictError("Campaign domain is not sendable")

            template_version = await repo.get_template_version_by_id(campaign.template_version_id)
            if template_version is None:
                raise NotFoundError("Template version not found")

            next_run_number = await repo.get_next_campaign_run_number(campaign.id)
            run = await repo.create_campaign_run(
                campaign_id=campaign.id,
                run_number=next_run_number,
                status="running",
            )
            await repo.update_campaign(
                campaign_id=campaign.id,
                values={
                    "status": "running",
                    "started_at": datetime.now(UTC),
                    "completed_at": None,
                },
            )

            await AuthRepository(uow.require_session()).write_audit_log(
                actor_type=actor.actor_type,
                actor_id=actor.user.id,
                action="campaign.launch",
                resource_type="campaign",
                resource_id=campaign.id,
                after_state={
                    "campaign_run_id": run.id,
                    "run_number": run.run_number,
                    "status": "running",
                },
                ip_address=ip_address,
                user_agent=user_agent,
            )

            refreshed_campaign = await repo.get_campaign_by_id(campaign.id)
            if refreshed_campaign is None:
                raise NotFoundError("Campaign not found")
            return refreshed_campaign, run, False

    async def _materialize_run_messages(self, *, campaign_id: str, campaign_run_id: str) -> int:
        async with UnitOfWork(self._session_factory) as uow:
            repo = CampaignRepository(uow.require_session())
            existing_messages = await repo.count_messages_for_run(campaign_run_id)
            if existing_messages > 0:
                return existing_messages

            campaign = await repo.get_campaign_by_id(campaign_id)
            if campaign is None:
                raise NotFoundError("Campaign not found")

            sender_profile = await repo.get_sender_profile_by_id(campaign.sender_profile_id)
            if sender_profile is None:
                raise NotFoundError("Sender profile not found")

            template_version = await repo.get_template_version_by_id(campaign.template_version_id)
            if template_version is None:
                raise NotFoundError("Template version not found")

            snapshots = await repo.list_included_snapshots_for_run(campaign_run_id)
            if not snapshots:
                await repo.update_campaign_run(
                    campaign_run_id=campaign_run_id,
                    values={"eligible_count": 0, "status": "completed"},
                )
                await repo.update_campaign(
                    campaign_id=campaign.id,
                    values={"total_eligible": 0, "status": "completed"},
                )
                return 0

            created_messages = 0
            batch_number = 1
            for idx in range(0, len(snapshots), _SEND_BATCH_SIZE):
                chunk = snapshots[idx : idx + _SEND_BATCH_SIZE]
                batch = await repo.create_send_batch(
                    campaign_run_id=campaign_run_id,
                    batch_number=batch_number,
                    batch_size=len(chunk),
                    sender_profile_id=sender_profile.id,
                    ip_pool_id=sender_profile.ip_pool_id,
                )
                batch_number += 1

                for snapshot in chunk:
                    if snapshot.contact_id is None:
                        continue

                    frozen_email = snapshot.frozen_attributes.get("email")
                    to_email = (
                        str(frozen_email).strip().lower()
                        if isinstance(frozen_email, str)
                        else None
                    )
                    if not to_email:
                        contact = await repo.get_contact_by_id(snapshot.contact_id)
                        if contact is None:
                            continue
                        to_email = contact.email.strip().lower()

                    await repo.create_message(
                        campaign_id=campaign.id,
                        send_batch_id=batch.id,
                        contact_id=snapshot.contact_id,
                        sender_profile_id=sender_profile.id,
                        domain_id=sender_profile.domain_id,
                        to_email=to_email,
                        from_email=sender_profile.from_email,
                        subject=template_version.subject,
                        headers={"campaign_run_id": campaign_run_id},
                    )
                    created_messages += 1

            await repo.update_campaign_run(
                campaign_run_id=campaign_run_id,
                values={"eligible_count": created_messages},
            )
            await repo.update_campaign(
                campaign_id=campaign.id,
                values={"total_eligible": created_messages},
            )
            return created_messages

    async def _refresh_campaign(self, campaign_id: str) -> Campaign:
        async with self._session_factory() as session:
            repo = CampaignRepository(session)
            campaign = await repo.get_campaign_by_id(campaign_id)
            if campaign is None:
                raise NotFoundError("Campaign not found")
            return campaign

    async def _refresh_run(self, campaign_run_id: str) -> CampaignRun:
        async with self._session_factory() as session:
            repo = CampaignRepository(session)
            run = await repo.get_campaign_run_by_id(campaign_run_id)
            if run is None:
                raise NotFoundError("Campaign run not found")
            return run

    async def _get_campaign_for_message(
        self,
        *,
        repo: CampaignRepository,
        message: Message,
    ) -> Campaign | None:
        if message.campaign_id is None:
            return None
        return await repo.get_campaign_by_id(message.campaign_id)

    def _build_contact_payload(self, *, contact: Any, snapshot: Any) -> dict[str, object]:
        payload: dict[str, object] = {
            "id": str(contact.id),
            "email": contact.email,
            "email_domain": contact.email_domain,
            "first_name": contact.first_name,
            "last_name": contact.last_name,
            "company": contact.company,
            "title": contact.title,
            "phone": contact.phone,
            "country_code": contact.country_code,
            "timezone": contact.timezone,
            "custom_attributes": dict(contact.custom_attributes or {}),
            "lifecycle_status": contact.lifecycle_status,
        }

        if snapshot is not None:
            frozen_attributes = dict(snapshot.frozen_attributes or {})
            if "first_name" in frozen_attributes:
                payload["first_name"] = frozen_attributes.get("first_name")
            if "last_name" in frozen_attributes:
                payload["last_name"] = frozen_attributes.get("last_name")
            if "email" in frozen_attributes:
                payload["email"] = frozen_attributes.get("email")
            if "email_domain" in frozen_attributes:
                payload["email_domain"] = frozen_attributes.get("email_domain")
        return payload

    def _render_template_string(self, template: str, contact_payload: dict[str, object]) -> str:
        try:
            compiled = self._renderer.from_string(template)
            rendered = compiled.render(contact=contact_payload)
        except (SecurityError, TemplateError) as exc:
            raise ValidationError("Template rendering failed") from exc

        if not isinstance(rendered, str):
            raise ValidationError("Template rendering failed")
        return rendered

    def _build_list_unsubscribe_headers(self, *, contact_id: str) -> list[tuple[str, str]]:
        token = self._unsubscribe_serializer.dumps({"contact_id": contact_id})
        base_url = self._settings.public_unsubscribe_base_url.rstrip("/")
        unsubscribe_url = f"{base_url}/unsubscribe?t={token}"
        return [
            ("List-Unsubscribe", f"<{unsubscribe_url}>"),
            ("List-Unsubscribe-Post", "List-Unsubscribe=One-Click"),
        ]

    @staticmethod
    def _is_spam_trap_candidate(email: str) -> bool:
        normalized = email.strip().lower()
        local_part, _, domain = normalized.partition("@")
        if not local_part or not domain:
            return True

        if domain in _SPAM_TRAP_SEED_DOMAINS:
            return True

        for fragment in _SPAM_TRAP_LOCAL_FRAGMENTS:
            if fragment in local_part:
                return True
        return False

    @staticmethod
    def _ml_spam_score_stub(message: Message) -> float:
        _ = message
        return 0.0

    @staticmethod
    def _fail_message(message: Message, *, error_code: str, error_message: str) -> None:
        message.status = "failed"
        message.error_code = error_code
        message.error_message = error_message[:4000]
        message.sent_at = None

    @staticmethod
    def _result_from_message(message: Message) -> MessageSendResult:
        return MessageSendResult(
            message_id=message.id,
            status=message.status,
            ses_message_id=message.ses_message_id,
            error_code=message.error_code,
            error_message=message.error_message,
        )

    def _resolve_domain_rate_limit_per_hour(self, rate_limit_per_hour: int | None) -> int:
        if isinstance(rate_limit_per_hour, int) and rate_limit_per_hour > 0:
            return rate_limit_per_hour
        return max(self._settings.default_domain_hourly_rate_limit, 1)

    @staticmethod
    def _require_admin(actor: CurrentActor) -> None:
        if actor.user.role != "admin":
            raise PermissionDeniedError("Admin role required")


@lru_cache(maxsize=1)
def get_campaign_service() -> CampaignService:
    return CampaignService(get_settings())


def reset_campaign_service_cache() -> None:
    get_campaign_service.cache_clear()
