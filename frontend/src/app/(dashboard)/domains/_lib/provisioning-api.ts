import type {
  DnsZone,
  ProvisioningAttempt,
  ProvisioningProvider,
  ProvisioningStatus,
  ProvisioningStep,
  ProvisioningStepStatus,
} from "@/types/domain";

type DomainContext = {
  id: string;
  name: string;
  dns_provider?: string | null;
};

export type DomainProvisioningStatusApiResponse = {
  domain_id?: string;
  domainId?: string;
  run_id?: string | null;
  runId?: string | null;
  status?: string | null;
  reason_code?: string | null;
  reasonCode?: string | null;
  started_at?: string | null;
  startedAt?: string | null;
  completed_at?: string | null;
  completedAt?: string | null;
  steps?: Array<{
    name?: string;
    status?: string;
    at?: string;
    message?: string | null;
  }>;
};

const STEP_LABELS: Record<string, string> = {
  queued: "Queued",
  start: "Start provisioning",
  create_ses: "Create SES identity",
  create_ses_identity: "Create SES identity",
  ensure_configuration_set: "Ensure configuration set",
  configure_mail_from: "Configure MAIL FROM",
  fetch_dkim: "Fetch DKIM tokens",
  sync_dns_records: "Fetch DKIM tokens",
  write_dns: "Write DNS records",
  apply_dns_records: "Write DNS records",
  verify_ses: "Verify SES identity",
  poll_ses_verification: "Verify SES identity",
  verify_dkim: "Verify DKIM",
  verify_dns_state: "Verify DKIM",
  already_verified: "Already verified",
  succeeded: "Done",
  failed: "Failed",
};

function normalizeProvider(value: string | null | undefined): ProvisioningProvider {
  if (value === "cloudflare") return "cloudflare";
  if (value === "route53") return "route53";
  return "manual";
}

function mapAttemptStatus(value: string | null | undefined): ProvisioningStatus {
  if (value === "verified" || value === "completed") return "completed";
  if (value === "failed") return "failed";
  if (value === "abandoned") return "abandoned";
  return "in_progress";
}

function mapStepStatus(value: string | null | undefined): ProvisioningStepStatus {
  if (value === "running") return "running";
  if (value === "failed") return "failed";
  if (value === "skipped") return "skipped";
  if (value === "completed" || value === "success" || value === "verified") {
    return "success";
  }
  return "pending";
}

function labelForStep(name: string): string {
  return STEP_LABELS[name] ?? name.replace(/_/g, " ");
}

function asStringOrNull(value: unknown): string | null {
  return typeof value === "string" && value.trim().length > 0 ? value : null;
}

function toProvisioningSteps(
  rawSteps: DomainProvisioningStatusApiResponse["steps"] | undefined,
): ProvisioningStep[] {
  const ordered: ProvisioningStep[] = [];
  const indexByKey = new Map<string, number>();

  for (const raw of rawSteps ?? []) {
    const key = raw.name?.trim();
    if (!key) continue;

    const mappedStatus = mapStepStatus(raw.status);
    const at = raw.at ?? null;
    const existingIndex = indexByKey.get(key);

    if (existingIndex === undefined) {
      indexByKey.set(key, ordered.length);
      ordered.push({
        key,
        label: labelForStep(key),
        status: mappedStatus,
        startedAt: mappedStatus === "pending" ? null : at,
        completedAt:
          mappedStatus === "success" || mappedStatus === "failed" || mappedStatus === "skipped"
            ? at
            : null,
        elapsedMs: null,
        errorDetail: mappedStatus === "failed" ? (raw.message ?? null) : null,
      });
      continue;
    }

    const step = ordered[existingIndex]!;
    step.status = mappedStatus;
    if (!step.startedAt && at) {
      step.startedAt = at;
    }
    if ((mappedStatus === "success" || mappedStatus === "failed" || mappedStatus === "skipped") && at) {
      step.completedAt = at;
    }
    if (mappedStatus === "failed" && raw.message) {
      step.errorDetail = raw.message;
    }
  }

  for (const step of ordered) {
    if (!step.startedAt || !step.completedAt) continue;
    const elapsed = new Date(step.completedAt).getTime() - new Date(step.startedAt).getTime();
    step.elapsedMs = Number.isFinite(elapsed) && elapsed >= 0 ? elapsed : null;
  }

  return ordered;
}

export function toProvisioningAttemptFromStatus(
  payload: DomainProvisioningStatusApiResponse,
  domain: DomainContext,
  previous: ProvisioningAttempt | null = null,
): ProvisioningAttempt {
  const steps = toProvisioningSteps(payload.steps);
  const status = mapAttemptStatus(payload.status);
  const startedAt =
    payload.started_at ??
    payload.startedAt ??
    steps[0]?.startedAt ??
    previous?.startedAt ??
    new Date().toISOString();
  const completedAt =
    payload.completed_at ??
    payload.completedAt ??
    (status === "completed" || status === "failed" ? steps.at(-1)?.completedAt ?? null : null);

  const failureReason = payload.reason_code ?? payload.reasonCode ?? null;
  const failedStep = steps.find((step) => step.status === "failed");

  return {
    id: payload.run_id ?? payload.runId ?? previous?.id ?? `prov-${domain.id}`,
    domainId: payload.domain_id ?? payload.domainId ?? domain.id,
    domainName: domain.name,
    provider: normalizeProvider(domain.dns_provider ?? previous?.provider),
    status,
    steps,
    startedAt,
    completedAt,
    failureReason,
    failureRemediation: failedStep?.errorDetail ?? previous?.failureRemediation ?? null,
  };
}

export function toDnsZones(
  payload: unknown,
  provider: Exclude<ProvisioningProvider, "manual">,
): DnsZone[] {
  const rawItems = Array.isArray(payload)
    ? payload
    : payload && typeof payload === "object" && Array.isArray((payload as { items?: unknown[] }).items)
      ? (payload as { items: unknown[] }).items
      : [];

  const zones: DnsZone[] = [];

  for (const item of rawItems) {
    if (typeof item === "string") {
      zones.push({ id: item, name: item, provider });
      continue;
    }
    if (!item || typeof item !== "object") continue;

    const row = item as Record<string, unknown>;
    const rowProvider = normalizeProvider(
      String(row.provider ?? row.dns_provider ?? provider),
    );
    if (rowProvider === "manual") continue;
    if (rowProvider !== provider) continue;

    const id = String(
      row.id ?? row.zone_id ?? row.hosted_zone_id ?? row.name ?? "",
    ).trim();
    if (!id) continue;

    const name = String(row.name ?? row.domain ?? id).trim();
    zones.push({
      id,
      name: name || id,
      provider: rowProvider,
    });
  }

  return zones.sort((a, b) => a.name.localeCompare(b.name));
}

export function toProvisioningAttempts(payload: unknown): ProvisioningAttempt[] {
  const rawItems = Array.isArray(payload)
    ? payload
    : payload && typeof payload === "object" && Array.isArray((payload as { items?: unknown[] }).items)
      ? (payload as { items: unknown[] }).items
      : [];

  return rawItems.flatMap((item, index) => {
    if (!item || typeof item !== "object") return [];
    const row = item as Record<string, unknown>;

    const domainId = String(row.domain_id ?? row.domainId ?? "").trim();
    const domainNameRaw =
      asStringOrNull(row.domain_name) ??
      asStringOrNull(row.domainName) ??
      domainId;
    const domainName = domainNameRaw || `domain-${index}`;
    const provider = normalizeProvider(
      String(row.provider ?? row.dns_provider ?? row.dnsProvider ?? "manual"),
    );

    const stepsPayload = Array.isArray(row.steps) ? row.steps : [];
    const steps = toProvisioningSteps(
      stepsPayload as DomainProvisioningStatusApiResponse["steps"],
    );
    const status = mapAttemptStatus(String(row.status ?? row.provisioning_status ?? "in_progress"));
    const startedAt =
      asStringOrNull(row.started_at) ??
      asStringOrNull(row.startedAt) ??
      steps[0]?.startedAt ??
      new Date().toISOString();
    const completedAtRaw = row.completed_at ?? row.completedAt ?? null;
    const completedAt =
      typeof completedAtRaw === "string"
        ? completedAtRaw
        : status === "completed" || status === "failed"
          ? steps.at(-1)?.completedAt ?? null
          : null;

    const failureReason =
      typeof row.failure_reason === "string"
        ? row.failure_reason
        : typeof row.reason_code === "string"
          ? row.reason_code
          : null;

    const failedStep = steps.find((step) => step.status === "failed");

    return [
      {
        id: String(row.id ?? row.run_id ?? `prov-${domainId || index}`),
        domainId: domainId || `domain-${index}`,
        domainName: domainName || domainId || `domain-${index}`,
        provider,
        status,
        steps,
        startedAt,
        completedAt,
        failureReason,
        failureRemediation:
          typeof row.failure_remediation === "string"
            ? row.failure_remediation
            : failedStep?.errorDetail ?? null,
      } satisfies ProvisioningAttempt,
    ];
  });
}
