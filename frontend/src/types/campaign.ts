export type CampaignStatus =
  | "draft"
  | "scheduled"
  | "running"
  | "paused"
  | "completed"
  | "cancelled"
  | "failed";

export type CampaignRecord = {
  id: string;
  name: string;
  audience: string;
  status: CampaignStatus;
  updatedAt: string;
};

export type CampaignKpis = {
  queued: number;
  sending: number;
  sent: number;
  delivered: number;
  bounced: number;
  complained: number;
  opened: number;
  clicked: number;
};

export type VelocityPoint = {
  label: string;
  value: number;
};

export type CampaignDetail = CampaignRecord & {
  domainId: string;
  kpis: CampaignKpis;
  velocityPoints: VelocityPoint[];
};

export type MessageStatus =
  | "queued"
  | "sending"
  | "sent"
  | "delivered"
  | "opened"
  | "clicked"
  | "bounced"
  | "complained"
  | "failed";

export type MessageEventType =
  | "queued"
  | "sent"
  | "delivered"
  | "opened"
  | "clicked"
  | "bounced"
  | "complained"
  | "failed";

export type MessageEvent = {
  id: string;
  type: MessageEventType;
  timestamp: string;
  detail: string | null;
};

export type CampaignMessage = {
  id: string;
  campaignId: string;
  email: string;
  status: MessageStatus;
  lastEventAt: string;
  hasBounce: boolean;
  hasClick: boolean;
  hasComplaint: boolean;
  sesMessageId: string | null;
};

export type CampaignMessageDetail = CampaignMessage & {
  contactId: string;
  senderProfileName: string;
  events: MessageEvent[];
  renderedHtml: string | null;
};

export type MessagesPage = {
  messages: CampaignMessage[];
  nextCursor: string | null;
};

export type CampaignDraft = {
  campaignId: string | null;
  name: string;
  tag: string;
  senderProfileId: string;
  templateId: string;
  templateVersion: number | null;
  audienceType: "segment" | "list";
  audienceId: string;
  scheduleType: "immediate" | "scheduled";
  scheduledAt: string;
  timezone: string;
};

export type PreflightSeverity = "ok" | "warning" | "critical";

export type PreflightCheck = {
  id: string;
  label: string;
  severity: PreflightSeverity;
  detail: string;
};

export const EMPTY_DRAFT: CampaignDraft = {
  campaignId: null,
  name: "",
  tag: "",
  senderProfileId: "",
  templateId: "",
  templateVersion: null,
  audienceType: "segment",
  audienceId: "",
  scheduleType: "immediate",
  scheduledAt: "",
  timezone: "UTC",
};

export const WIZARD_STEPS = [
  "Details",
  "Sender",
  "Template",
  "Audience",
  "Schedule",
  "Review",
] as const;

export function isDraftStepComplete(
  step: number,
  draft: CampaignDraft,
): boolean {
  switch (step) {
    case 0:
      return draft.name.trim().length > 0;
    case 1:
      return draft.senderProfileId !== "";
    case 2:
      return draft.templateId !== "" && draft.templateVersion !== null;
    case 3:
      return draft.audienceId !== "";
    case 4:
      return draft.scheduleType === "immediate" || draft.scheduledAt !== "";
    default:
      return true;
  }
}
