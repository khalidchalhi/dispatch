import type { SuppressionEntry, SuppressionReason, SuppressionSource } from "@/types/suppression";

type ApiSuppressionReasonCode =
  | "hard_bounce"
  | "complaint"
  | "unsubscribe"
  | "manual"
  | "spam_trap"
  | "role_account"
  | "global_suppression_sync";

export type ApiSuppressionEntryResponse = {
  id: string;
  email: string;
  reason_code: ApiSuppressionReasonCode;
  source: string;
  first_suppressed_at: string;
  expires_at: string | null;
};

export type ApiSuppressionListResponse = {
  items: ApiSuppressionEntryResponse[];
  total: number;
  limit: number;
  offset: number;
};

export type ApiSuppressionRevealResponse = {
  id: string;
  email: string;
};

function toSuppressionReason(reasonCode: ApiSuppressionReasonCode): SuppressionReason {
  switch (reasonCode) {
    case "hard_bounce":
      return "hard_bounce";
    case "complaint":
    case "spam_trap":
      return "spam_complaint";
    case "unsubscribe":
      return "unsubscribe";
    case "manual":
    case "role_account":
    case "global_suppression_sync":
    default:
      return "manual";
  }
}

function toSuppressionSource(source: string): SuppressionSource {
  const normalized = source.trim().toLowerCase();
  if (normalized.includes("ses")) return "ses_event";
  if (normalized.includes("one_click")) return "one_click";
  if (normalized.includes("csv")) return "csv_import";
  if (normalized.includes("api")) return "api";
  return "manual";
}

export function toSuppressionEntry(api: ApiSuppressionEntryResponse): SuppressionEntry {
  return {
    id: api.id,
    email: api.email,
    reason: toSuppressionReason(api.reason_code),
    source: toSuppressionSource(api.source),
    note: null,
    createdAt: api.first_suppressed_at,
  };
}
