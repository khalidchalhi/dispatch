import type { BreakerEntry, BreakerEntryState, BreakerScope } from "@/types/ops";

type ApiBreakerEntry = {
  id?: string;
  breaker_id?: string;
  scope?: string;
  scope_type?: string;
  scopeType?: string;
  entity_id?: string;
  entityId?: string;
  scope_id?: string;
  scopeId?: string;
  entity_name?: string;
  entityName?: string;
  state?: string;
  tripped_at?: string | null;
  trippedAt?: string | null;
  reason?: string | null;
  tripped_reason?: string | null;
  bounce_rate_pct?: number | null;
  bounceRatePct?: number | null;
  complaint_rate_pct?: number | null;
  complaintRatePct?: number | null;
  auto_reset_at?: string | null;
  autoResetAt?: string | null;
  updated_at?: string;
  updatedAt?: string;
};

export type BreakerListApiResponse = {
  items?: ApiBreakerEntry[];
};

function normalizeScope(value: string | undefined): BreakerScope {
  if (value === "domain") return "domain";
  if (value === "ip_pool") return "ip_pool";
  if (value === "sender_profile") return "sender_profile";
  return "account";
}

function normalizeState(value: string | undefined): BreakerEntryState {
  if (value === "open") return "open";
  if (value === "half_open" || value === "half-open") return "half_open";
  return "closed";
}

function entityHref(scope: BreakerScope, entityId: string): string {
  if (scope === "domain") return `/domains/${entityId}`;
  if (scope === "sender_profile") return `/sender-profiles/${entityId}`;
  if (scope === "ip_pool") return "/sender-profiles";
  return "/settings";
}

function entityName(scope: BreakerScope, entityId: string, fallback?: string) {
  if (fallback && fallback.trim().length > 0) return fallback;
  if (scope === "account") return "Platform account";
  return entityId;
}

function coercePct(value: number | null | undefined): number | null {
  if (typeof value !== "number" || Number.isNaN(value)) return null;
  // Backend metrics are often ratios in [0..1]; UI expects percentages.
  return value <= 1 ? value * 100 : value;
}

export function toBreakerEntry(item: ApiBreakerEntry, index: number): BreakerEntry {
  const scope = normalizeScope(item.scope ?? item.scope_type ?? item.scopeType);
  const entityId =
    item.entity_id ??
    item.entityId ??
    item.scope_id ??
    item.scopeId ??
    `entity-${index}`;

  return {
    id: item.id ?? item.breaker_id ?? `${scope}-${entityId}`,
    scope,
    entityId,
    entityName: entityName(scope, entityId, item.entity_name ?? item.entityName),
    entityHref: entityHref(scope, entityId),
    state: normalizeState(item.state),
    trippedAt: item.tripped_at ?? item.trippedAt ?? null,
    reason: item.reason ?? item.tripped_reason ?? null,
    bounceRatePct: coercePct(item.bounce_rate_pct ?? item.bounceRatePct),
    complaintRatePct: coercePct(item.complaint_rate_pct ?? item.complaintRatePct),
    autoResetAt: item.auto_reset_at ?? item.autoResetAt ?? null,
    updatedAt: item.updated_at ?? item.updatedAt ?? new Date().toISOString(),
  };
}

export function toBreakerEntries(response: BreakerListApiResponse): BreakerEntry[] {
  return (response.items ?? []).map(toBreakerEntry);
}
