from __future__ import annotations

from datetime import datetime

from pydantic import AliasChoices, BaseModel, ConfigDict, Field

from libs.core.campaigns.models import Campaign, CampaignRun, Message


class CampaignResponse(BaseModel):
    id: str
    name: str
    status: str
    campaign_type: str
    sender_profile_id: str
    template_version_id: str
    segment_id: str | None
    list_id: str | None
    send_rate_per_hour: int
    started_at: datetime | None
    completed_at: datetime | None
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_model(cls, campaign: Campaign) -> CampaignResponse:
        return cls(
            id=campaign.id,
            name=campaign.name,
            status=campaign.status,
            campaign_type=campaign.campaign_type,
            sender_profile_id=campaign.sender_profile_id,
            template_version_id=campaign.template_version_id,
            segment_id=campaign.segment_id,
            list_id=campaign.list_id,
            send_rate_per_hour=campaign.send_rate_per_hour,
            started_at=campaign.started_at,
            completed_at=campaign.completed_at,
            created_at=campaign.created_at,
            updated_at=campaign.updated_at,
        )


class CampaignListResponse(BaseModel):
    items: list[CampaignResponse]
    total: int
    limit: int
    offset: int


class CampaignCreateRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    name: str = Field(min_length=1, max_length=255)
    campaign_type: str = Field(
        default="outreach",
        min_length=1,
        max_length=30,
        validation_alias=AliasChoices("campaign_type", "campaignType"),
    )
    sender_profile_id: str = Field(
        validation_alias=AliasChoices("sender_profile_id", "senderProfileId")
    )
    template_version_id: str | None = Field(
        default=None,
        validation_alias=AliasChoices("template_version_id", "templateVersionId"),
    )
    template_id: str | None = Field(
        default=None,
        validation_alias=AliasChoices("template_id", "templateId"),
    )
    template_version: int | None = Field(
        default=None,
        ge=1,
        validation_alias=AliasChoices("template_version", "templateVersion"),
    )
    segment_id: str | None = Field(
        default=None,
        validation_alias=AliasChoices("segment_id", "segmentId"),
    )
    list_id: str | None = Field(
        default=None,
        validation_alias=AliasChoices("list_id", "listId"),
    )
    audience_type: str | None = Field(
        default=None,
        validation_alias=AliasChoices("audience_type", "audienceType"),
    )
    audience_id: str | None = Field(
        default=None,
        validation_alias=AliasChoices("audience_id", "audienceId"),
    )
    schedule_type: str = Field(
        default="immediate",
        validation_alias=AliasChoices("schedule_type", "scheduleType"),
    )
    scheduled_at: datetime | None = Field(
        default=None,
        validation_alias=AliasChoices("scheduled_at", "scheduledAt"),
    )
    timezone: str = Field(default="UTC", max_length=120)
    send_rate_per_hour: int = Field(
        default=100,
        ge=1,
        le=100000,
        validation_alias=AliasChoices("send_rate_per_hour", "sendRatePerHour"),
    )
    tracking_opens: bool = Field(
        default=False,
        validation_alias=AliasChoices("tracking_opens", "trackingOpens"),
    )
    tracking_clicks: bool = Field(
        default=False,
        validation_alias=AliasChoices("tracking_clicks", "trackingClicks"),
    )


class CampaignUpdateRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=255)
    campaign_type: str | None = Field(
        default=None,
        min_length=1,
        max_length=30,
        validation_alias=AliasChoices("campaign_type", "campaignType"),
    )
    sender_profile_id: str | None = Field(
        default=None,
        validation_alias=AliasChoices("sender_profile_id", "senderProfileId"),
    )
    template_version_id: str | None = Field(
        default=None,
        validation_alias=AliasChoices("template_version_id", "templateVersionId"),
    )
    template_id: str | None = Field(
        default=None,
        validation_alias=AliasChoices("template_id", "templateId"),
    )
    template_version: int | None = Field(
        default=None,
        ge=1,
        validation_alias=AliasChoices("template_version", "templateVersion"),
    )
    segment_id: str | None = Field(
        default=None,
        validation_alias=AliasChoices("segment_id", "segmentId"),
    )
    list_id: str | None = Field(
        default=None,
        validation_alias=AliasChoices("list_id", "listId"),
    )
    audience_type: str | None = Field(
        default=None,
        validation_alias=AliasChoices("audience_type", "audienceType"),
    )
    audience_id: str | None = Field(
        default=None,
        validation_alias=AliasChoices("audience_id", "audienceId"),
    )
    schedule_type: str | None = Field(
        default=None,
        validation_alias=AliasChoices("schedule_type", "scheduleType"),
    )
    scheduled_at: datetime | None = Field(
        default=None,
        validation_alias=AliasChoices("scheduled_at", "scheduledAt"),
    )
    timezone: str | None = Field(default=None, max_length=120)
    send_rate_per_hour: int | None = Field(
        default=None,
        ge=1,
        le=100000,
        validation_alias=AliasChoices("send_rate_per_hour", "sendRatePerHour"),
    )
    tracking_opens: bool | None = Field(
        default=None,
        validation_alias=AliasChoices("tracking_opens", "trackingOpens"),
    )
    tracking_clicks: bool | None = Field(
        default=None,
        validation_alias=AliasChoices("tracking_clicks", "trackingClicks"),
    )


class CampaignLaunchResponse(BaseModel):
    campaign: CampaignResponse
    campaign_run_id: str
    run_number: int
    snapshot_rows: int
    created_messages: int
    enqueued_messages: int
    already_launched: bool

    @classmethod
    def build(
        cls,
        *,
        campaign: Campaign,
        campaign_run: CampaignRun,
        snapshot_rows: int,
        created_messages: int,
        enqueued_messages: int,
        already_launched: bool,
    ) -> CampaignLaunchResponse:
        return cls(
            campaign=CampaignResponse.from_model(campaign),
            campaign_run_id=campaign_run.id,
            run_number=campaign_run.run_number,
            snapshot_rows=snapshot_rows,
            created_messages=created_messages,
            enqueued_messages=enqueued_messages,
            already_launched=already_launched,
        )


class CampaignStateChangeResponse(BaseModel):
    campaign: CampaignResponse
    enqueued_messages: int = 0
    cancelled_queued_messages: int = 0


class CampaignPreflightCheckResponse(BaseModel):
    id: str
    label: str
    severity: str
    detail: str


class CampaignPreflightResponse(BaseModel):
    campaign_id: str
    checks: list[CampaignPreflightCheckResponse]
    has_critical: bool
    generated_at: datetime


class CampaignMessageListItem(BaseModel):
    message_id: str
    campaign_id: str | None = None
    to_email: str
    status: str
    created_at: datetime
    sent_at: datetime | None = None
    delivered_at: datetime | None = None
    bounce_type: str | None = None
    complaint_type: str | None = None
    error_code: str | None = None
    error_message: str | None = None
    has_bounce: bool
    has_click: bool
    has_complaint: bool
    ses_message_id: str | None = None
    last_event_at: datetime


class CampaignMessageListResponse(BaseModel):
    items: list[CampaignMessageListItem]
    next_cursor: str | None = None


class MessageSendResultResponse(BaseModel):
    message_id: str
    status: str
    ses_message_id: str | None = None
    error_code: str | None = None
    error_message: str | None = None

    @classmethod
    def from_model(cls, message: Message) -> MessageSendResultResponse:
        return cls(
            message_id=message.id,
            status=message.status,
            ses_message_id=message.ses_message_id,
            error_code=message.error_code,
            error_message=message.error_message,
        )
