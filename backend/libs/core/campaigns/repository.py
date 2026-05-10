from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import and_, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from libs.core.campaigns.models import Campaign, CampaignRun, Message, SendBatch
from libs.core.contacts.models import Contact, SubscriptionStatus
from libs.core.db.pagination import decode_cursor
from libs.core.domains.models import Domain
from libs.core.segments.models import SegmentSnapshot
from libs.core.sender_profiles.models import SenderProfile
from libs.core.suppression.models import SuppressionEntry
from libs.core.templates.models import TemplateVersion


@dataclass(frozen=True, slots=True)
class QueuedMessageDispatchTarget:
    message_id: str
    domain_id: str
    domain_name: str


@dataclass(frozen=True, slots=True)
class MessageDispatchContext:
    message_id: str
    status: str
    error_code: str | None
    domain_id: str
    domain_name: str
    domain_rate_limit_per_hour: int


class CampaignRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_campaign_by_id(self, campaign_id: str) -> Campaign | None:
        stmt = select(Campaign).where(Campaign.id == campaign_id)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_campaigns(
        self,
        *,
        limit: int,
        offset: int,
        status: str | None = None,
    ) -> list[Campaign]:
        stmt = select(Campaign)
        if status is not None:
            stmt = stmt.where(Campaign.status == status)
        stmt = stmt.order_by(Campaign.updated_at.desc(), Campaign.id.desc())
        stmt = stmt.limit(limit).offset(offset)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def count_campaigns(self, *, status: str | None = None) -> int:
        stmt = select(func.count()).select_from(Campaign)
        if status is not None:
            stmt = stmt.where(Campaign.status == status)
        result = await self.session.execute(stmt)
        return int(result.scalar_one())

    async def update_campaign(self, *, campaign_id: str, values: dict[str, object]) -> bool:
        if not values:
            return False
        values_with_timestamp = dict(values)
        values_with_timestamp["updated_at"] = datetime.now(UTC)
        stmt = (
            update(Campaign)
            .where(Campaign.id == campaign_id)
            .values(**values_with_timestamp)
            .execution_options(synchronize_session="fetch")
        )
        result = await self.session.execute(stmt)
        return bool(getattr(result, "rowcount", 0))

    async def get_campaign_run_by_id(self, campaign_run_id: str) -> CampaignRun | None:
        stmt = select(CampaignRun).where(CampaignRun.id == campaign_run_id)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_latest_campaign_run_for_campaign(self, campaign_id: str) -> CampaignRun | None:
        stmt = (
            select(CampaignRun)
            .where(CampaignRun.campaign_id == campaign_id)
            .order_by(CampaignRun.run_number.desc(), CampaignRun.started_at.desc())
            .limit(1)
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_next_campaign_run_number(self, campaign_id: str) -> int:
        stmt = select(func.max(CampaignRun.run_number)).where(
            CampaignRun.campaign_id == campaign_id
        )
        result = await self.session.execute(stmt)
        max_run_number = result.scalar_one_or_none()
        if max_run_number is None:
            return 1
        return int(max_run_number) + 1

    async def create_campaign_run(
        self,
        *,
        campaign_id: str,
        run_number: int,
        status: str,
    ) -> CampaignRun:
        run = CampaignRun(
            campaign_id=campaign_id,
            run_number=run_number,
            status=status,
        )
        self.session.add(run)
        await self.session.flush()
        return run

    async def update_campaign_run(
        self,
        *,
        campaign_run_id: str,
        values: dict[str, object],
    ) -> bool:
        if not values:
            return False
        stmt = (
            update(CampaignRun)
            .where(CampaignRun.id == campaign_run_id)
            .values(**values)
            .execution_options(synchronize_session="fetch")
        )
        result = await self.session.execute(stmt)
        return bool(getattr(result, "rowcount", 0))

    async def get_sender_profile_by_id(self, sender_profile_id: str) -> SenderProfile | None:
        stmt = select(SenderProfile).where(SenderProfile.id == sender_profile_id)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_domain_by_id(self, domain_id: str) -> Domain | None:
        stmt = select(Domain).where(Domain.id == domain_id)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_template_version_by_id(self, template_version_id: str) -> TemplateVersion | None:
        stmt = select(TemplateVersion).where(TemplateVersion.id == template_version_id)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_template_version_by_template_and_number(
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

    async def count_included_snapshots_for_run(self, campaign_run_id: str) -> int:
        stmt = (
            select(func.count())
            .select_from(SegmentSnapshot)
            .where(SegmentSnapshot.campaign_run_id == campaign_run_id)
            .where(SegmentSnapshot.included.is_(True))
        )
        result = await self.session.execute(stmt)
        return int(result.scalar_one())

    async def list_included_snapshots_for_run(self, campaign_run_id: str) -> list[SegmentSnapshot]:
        stmt = (
            select(SegmentSnapshot)
            .where(SegmentSnapshot.campaign_run_id == campaign_run_id)
            .where(SegmentSnapshot.included.is_(True))
            .order_by(SegmentSnapshot.id.asc())
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def create_send_batch(
        self,
        *,
        campaign_run_id: str,
        batch_number: int,
        batch_size: int,
        sender_profile_id: str,
        ip_pool_id: str | None,
    ) -> SendBatch:
        batch = SendBatch(
            campaign_run_id=campaign_run_id,
            batch_number=batch_number,
            batch_size=batch_size,
            sender_profile_id=sender_profile_id,
            ip_pool_id=ip_pool_id,
            status="queued",
        )
        self.session.add(batch)
        await self.session.flush()
        return batch

    async def mark_batches_enqueued(self, campaign_run_id: str) -> int:
        stmt = (
            update(SendBatch)
            .where(SendBatch.campaign_run_id == campaign_run_id)
            .values(enqueued_at=datetime.now(UTC))
            .execution_options(synchronize_session="fetch")
        )
        result = await self.session.execute(stmt)
        return int(getattr(result, "rowcount", 0) or 0)

    async def create_message(
        self,
        *,
        campaign_id: str,
        send_batch_id: str,
        contact_id: str,
        sender_profile_id: str,
        domain_id: str,
        to_email: str,
        from_email: str,
        subject: str,
        headers: dict[str, object],
    ) -> Message:
        message = Message(
            campaign_id=campaign_id,
            send_batch_id=send_batch_id,
            contact_id=contact_id,
            sender_profile_id=sender_profile_id,
            domain_id=domain_id,
            to_email=to_email,
            from_email=from_email,
            subject=subject,
            status="queued",
            headers=headers,
        )
        self.session.add(message)
        await self.session.flush()
        return message

    async def count_messages_for_run(self, campaign_run_id: str) -> int:
        stmt = (
            select(func.count())
            .select_from(Message)
            .join(SendBatch, Message.send_batch_id == SendBatch.id)
            .where(SendBatch.campaign_run_id == campaign_run_id)
        )
        result = await self.session.execute(stmt)
        return int(result.scalar_one())

    async def list_messages_for_run(self, campaign_run_id: str) -> list[Message]:
        stmt = (
            select(Message)
            .join(SendBatch, Message.send_batch_id == SendBatch.id)
            .where(SendBatch.campaign_run_id == campaign_run_id)
            .order_by(Message.created_at.asc(), Message.id.asc())
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def list_messages_for_campaign(
        self,
        *,
        campaign_id: str,
        limit: int,
        cursor: str | None,
        status: str | None = None,
    ) -> list[Message]:
        stmt = select(Message).where(Message.campaign_id == campaign_id)
        if status is not None:
            stmt = stmt.where(Message.status == status)

        if cursor:
            cursor_created_at, cursor_id = decode_cursor(cursor)
            stmt = stmt.where(
                or_(
                    Message.created_at < cursor_created_at,
                    and_(
                        Message.created_at == cursor_created_at,
                        Message.id < cursor_id,
                    ),
                )
            )

        stmt = stmt.order_by(Message.created_at.desc(), Message.id.desc())
        stmt = stmt.limit(limit + 1)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def list_queued_message_ids_for_run(self, campaign_run_id: str) -> list[str]:
        stmt = (
            select(Message.id)
            .join(SendBatch, Message.send_batch_id == SendBatch.id)
            .where(SendBatch.campaign_run_id == campaign_run_id)
            .where(Message.status == "queued")
            .order_by(Message.id.asc())
        )
        result = await self.session.execute(stmt)
        return [str(item[0]) for item in result.all()]

    async def list_queued_message_dispatch_targets_for_run(
        self,
        campaign_run_id: str,
    ) -> list[QueuedMessageDispatchTarget]:
        stmt = (
            select(Message.id, Message.domain_id, Domain.name)
            .join(SendBatch, Message.send_batch_id == SendBatch.id)
            .join(Domain, Domain.id == Message.domain_id)
            .where(SendBatch.campaign_run_id == campaign_run_id)
            .where(Message.status == "queued")
            .order_by(Message.id.asc())
        )
        result = await self.session.execute(stmt)
        return [
            QueuedMessageDispatchTarget(
                message_id=str(row[0]),
                domain_id=str(row[1]),
                domain_name=str(row[2]),
            )
            for row in result.all()
        ]

    async def get_message_by_id(self, message_id: str) -> Message | None:
        stmt = select(Message).where(Message.id == message_id)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_message_dispatch_context(self, message_id: str) -> MessageDispatchContext | None:
        stmt = (
            select(
                Message.id,
                Message.status,
                Message.error_code,
                Message.domain_id,
                Domain.name,
                Domain.rate_limit_per_hour,
            )
            .join(Domain, Domain.id == Message.domain_id)
            .where(Message.id == message_id)
            .limit(1)
        )
        result = await self.session.execute(stmt)
        row = result.first()
        if row is None:
            return None
        return MessageDispatchContext(
            message_id=str(row[0]),
            status=str(row[1]),
            error_code=str(row[2]) if row[2] is not None else None,
            domain_id=str(row[3]),
            domain_name=str(row[4]),
            domain_rate_limit_per_hour=int(row[5]),
        )

    async def claim_message_for_sending(self, message_id: str) -> bool:
        stmt = (
            update(Message)
            .where(Message.id == message_id)
            .where(Message.status == "queued")
            .values(status="sending")
            .execution_options(synchronize_session="fetch")
        )
        result = await self.session.execute(stmt)
        return bool(getattr(result, "rowcount", 0))

    async def find_active_suppression_by_email(self, email: str) -> SuppressionEntry | None:
        stmt = (
            select(SuppressionEntry)
            .where(func.lower(SuppressionEntry.email) == email.lower())
            .where(
                or_(
                    SuppressionEntry.expires_at.is_(None),
                    SuppressionEntry.expires_at > datetime.now(UTC),
                )
            )
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_subscription_status_for_contact(
        self,
        contact_id: str,
        *,
        channel: str = "email",
    ) -> SubscriptionStatus | None:
        stmt = (
            select(SubscriptionStatus)
            .where(SubscriptionStatus.contact_id == contact_id)
            .where(SubscriptionStatus.channel == channel)
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_contact_by_id(self, contact_id: str) -> Contact | None:
        stmt = select(Contact).where(Contact.id == contact_id)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def increment_campaign_run_sent_count(self, campaign_run_id: str) -> bool:
        stmt = (
            update(CampaignRun)
            .where(CampaignRun.id == campaign_run_id)
            .values(sent_count=CampaignRun.sent_count + 1)
            .execution_options(synchronize_session="fetch")
        )
        result = await self.session.execute(stmt)
        return bool(getattr(result, "rowcount", 0))

    async def increment_campaign_total_sent(self, campaign_id: str) -> bool:
        stmt = (
            update(Campaign)
            .where(Campaign.id == campaign_id)
            .values(
                total_sent=Campaign.total_sent + 1,
                updated_at=datetime.now(UTC),
            )
            .execution_options(synchronize_session="fetch")
        )
        result = await self.session.execute(stmt)
        return bool(getattr(result, "rowcount", 0))

    async def cancel_queued_messages_for_campaign(self, campaign_id: str) -> int:
        stmt = (
            update(Message)
            .where(Message.campaign_id == campaign_id)
            .where(Message.status == "queued")
            .values(
                status="failed",
                error_code="campaign_cancelled",
                error_message="Campaign cancelled before send",
            )
            .execution_options(synchronize_session="fetch")
        )
        result = await self.session.execute(stmt)
        return int(getattr(result, "rowcount", 0) or 0)

    async def get_campaign_run_by_message_id(self, message_id: str) -> CampaignRun | None:
        stmt = (
            select(CampaignRun)
            .join(SendBatch, SendBatch.campaign_run_id == CampaignRun.id)
            .join(Message, Message.send_batch_id == SendBatch.id)
            .where(Message.id == message_id)
            .limit(1)
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_segment_snapshot_for_message(self, message_id: str) -> SegmentSnapshot | None:
        stmt = (
            select(SegmentSnapshot)
            .join(SendBatch, SendBatch.campaign_run_id == SegmentSnapshot.campaign_run_id)
            .join(Message, Message.send_batch_id == SendBatch.id)
            .where(Message.id == message_id)
            .where(
                and_(
                    SegmentSnapshot.contact_id == Message.contact_id,
                    SegmentSnapshot.included.is_(True),
                )
            )
            .limit(1)
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()
