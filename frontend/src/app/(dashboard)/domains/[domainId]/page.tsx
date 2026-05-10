import Link from "next/link";
import { notFound } from "next/navigation";
import { Badge } from "@/components/ui/badge";
import { SectionPanel } from "@/components/patterns/section-panel";
import { serverJson } from "@/lib/api/server";
import { apiEndpoints as ENDPOINTS } from "@/lib/api/endpoints";
import { formatTimestamp } from "@/lib/formatters";
import { ApiError } from "@/lib/api/errors";
import { getThrottleStatus, getDenialEvents } from "../_lib/domains-queries";
import { CircuitBreakerBadge } from "@/components/shared/circuit-breaker-badge";
import { DnsRecords } from "../_components/dns-records";
import { DomainRetireButton } from "../_components/domain-retire-button";
import { VerifyButton } from "../_components/verify-button";
import { ThroughputTab } from "./_components/throughput-tab";
import { WarmupTab } from "./_components/warmup-tab";
import { ReputationTab } from "./_components/reputation-tab";
import type {
  DnsRecordStatus,
  DomainDetail,
  DomainStatus,
  PostmasterData,
  PostmasterReputation,
  WarmupDay,
  WarmupPreset,
  WarmupStatus,
} from "@/types/domain";

const statusVariant = {
  pending: "muted",
  verifying: "warning",
  verified: "success",
  cooling: "warning",
  burnt: "danger",
  retired: "outline",
} as const;

type DomainDetailApiResponse = {
  id: string;
  name: string;
  verification_status: string;
  reputation_status: string;
  created_at: string;
  updated_at: string;
  dns_records: Array<{
    id: string;
    record_type: string;
    name: string;
    value: string;
    purpose: string;
    verification_status: string;
    last_verified_at: string | null;
  }>;
};

type WarmupApiResponse = {
  domain_id?: string;
  domainId?: string;
  lifecycle?: string;
  warmup_stage?: string;
  current_day?: number;
  currentDay?: number;
  total_days?: number;
  totalDays?: number;
  today_cap?: number;
  todayCap?: number;
  today_sends?: number;
  todaySends?: number;
  scheduled_graduation_at?: string | null;
  scheduledGraduationAt?: string | null;
  graduated_at?: string | null;
  graduatedAt?: string | null;
  warmup_completed_at?: string | null;
  schedule?: {
    preset?: string;
    total_days?: number;
    totalDays?: number;
    days?: Array<{
      day?: number;
      cap?: number;
      actual_sends?: number | null;
      actualSends?: number | null;
    }>;
    volumes?: number[];
  };
  volumes?: number[];
};

type PostmasterApiResponse = {
  connected?: boolean;
  as_of?: string | null;
  asOf?: string | null;
  last_updated_at?: string | null;
  metrics?: Array<Record<string, unknown>>;
  items?: Array<Record<string, unknown>>;
};

function toDomainStatus(
  verificationStatus: string,
  reputationStatus: string,
): DomainStatus {
  if (reputationStatus === "retired") return "retired";
  if (reputationStatus === "burnt") return "burnt";
  if (reputationStatus === "cooling") return "cooling";
  if (verificationStatus === "verified") return "verified";
  if (verificationStatus === "pending") return "pending";
  return "verifying";
}

function toDnsRecordStatus(status: string): DnsRecordStatus {
  if (status === "verified") return "valid";
  if (status === "failed") return "invalid";
  return "pending";
}

function toDomainDetail(api: DomainDetailApiResponse): DomainDetail {
  return {
    id: api.id,
    name: api.name,
    status: toDomainStatus(api.verification_status, api.reputation_status),
    breaker: "closed",
    createdAt: api.created_at,
    updatedAt: api.updated_at,
    dnsRecords: api.dns_records.map((record) => ({
      id: record.id,
      type:
        record.record_type === "TXT" ||
        record.record_type === "CNAME" ||
        record.record_type === "MX"
          ? record.record_type
          : "TXT",
      hostname: record.name,
      value: record.value,
      purpose:
        record.purpose === "spf" ||
        record.purpose === "dkim" ||
        record.purpose === "dmarc" ||
        record.purpose === "mail_from"
          ? record.purpose
          : "mail_from",
      status: toDnsRecordStatus(record.verification_status),
      lastCheckedAt: record.last_verified_at,
    })),
  };
}

function toNumber(value: unknown, fallback = 0): number {
  if (typeof value === "number" && Number.isFinite(value)) return value;
  if (typeof value === "string") {
    const parsed = Number.parseFloat(value);
    if (Number.isFinite(parsed)) return parsed;
  }
  return fallback;
}

function toPct(value: unknown): number {
  const numeric = toNumber(value, 0);
  return numeric <= 1 ? numeric * 100 : numeric;
}

function normalizePreset(value: string | undefined): WarmupPreset {
  if (value === "conservative" || value === "aggressive" || value === "custom") {
    return value;
  }
  return "standard";
}

function normalizeReputation(value: unknown): PostmasterReputation {
  if (value === "high" || value === "medium" || value === "low" || value === "bad") {
    return value;
  }
  return "medium";
}

function buildWarmupDays(
  payload: WarmupApiResponse,
  currentDay: number,
): WarmupDay[] {
  const scheduleDays = payload.schedule?.days;
  if (Array.isArray(scheduleDays) && scheduleDays.length > 0) {
    return scheduleDays.map((entry, index) => ({
      day: toNumber(entry.day, index + 1),
      cap: toNumber(entry.cap, 0),
      actualSends:
        entry.actual_sends === null || entry.actualSends === null
          ? null
          : entry.actual_sends !== undefined || entry.actualSends !== undefined
            ? toNumber(entry.actual_sends ?? entry.actualSends, 0)
            : index < currentDay
              ? 0
              : null,
    }));
  }

  const volumes = payload.schedule?.volumes ?? payload.volumes ?? [];
  if (Array.isArray(volumes) && volumes.length > 0) {
    return volumes.map((cap, index) => ({
      day: index + 1,
      cap: toNumber(cap, 0),
      actualSends: index < currentDay ? 0 : null,
    }));
  }

  return [];
}

function toWarmupStatus(payload: WarmupApiResponse, domainId: string): WarmupStatus {
  const currentDay = toNumber(payload.current_day ?? payload.currentDay, 0);
  const days = buildWarmupDays(payload, currentDay);
  const totalDays = toNumber(
    payload.total_days ?? payload.totalDays ?? payload.schedule?.total_days ?? payload.schedule?.totalDays,
    days.length,
  );

  return {
    domainId: payload.domain_id ?? payload.domainId ?? domainId,
    lifecycle:
      payload.lifecycle === "warming" ||
      payload.lifecycle === "healthy" ||
      payload.lifecycle === "cooling" ||
      payload.lifecycle === "burnt" ||
      payload.lifecycle === "retired"
        ? payload.lifecycle
        : payload.warmup_stage === "warming"
          ? "warming"
          : payload.warmup_stage === "graduated"
            ? "healthy"
            : "warming",
    currentDay,
    totalDays: totalDays > 0 ? totalDays : days.length,
    todayCap: toNumber(payload.today_cap ?? payload.todayCap, days[currentDay - 1]?.cap ?? 0),
    todaySends: toNumber(payload.today_sends ?? payload.todaySends, 0),
    scheduledGraduationAt:
      payload.scheduled_graduation_at ?? payload.scheduledGraduationAt ?? null,
    graduatedAt:
      payload.graduated_at ?? payload.graduatedAt ?? payload.warmup_completed_at ?? null,
    schedule: {
      preset: normalizePreset(payload.schedule?.preset),
      totalDays: totalDays > 0 ? totalDays : days.length,
      days,
    },
  };
}

function toPostmasterData(payload: PostmasterApiResponse, domainId: string): PostmasterData {
  const rows = payload.metrics ?? payload.items ?? [];
  const metrics = rows.map((row, index) => {
    const dateRaw = row["date"];
    const date =
      typeof dateRaw === "string" && dateRaw.length > 0
        ? dateRaw
        : `day-${index + 1}`;

    return {
      date,
      spamRatePct: toPct(
        row["spam_rate_pct"] ?? row["spam_rate"] ?? row["spamRatePct"],
      ),
      domainReputation: normalizeReputation(
        row["domain_reputation"] ?? row["domainReputation"],
      ),
      spfPassPct: toPct(
        row["spf_pass_pct"] ?? row["spf_success_ratio"] ?? row["spfPassPct"],
      ),
      dkimPassPct: toPct(
        row["dkim_pass_pct"] ?? row["dkim_success_ratio"] ?? row["dkimPassPct"],
      ),
      dmarcPassPct: toPct(
        row["dmarc_pass_pct"] ?? row["dmarc_success_ratio"] ?? row["dmarcPassPct"],
      ),
    };
  });

  return {
    domainId,
    connected: payload.connected ?? metrics.length > 0,
    asOf: payload.as_of ?? payload.asOf ?? payload.last_updated_at ?? null,
    metrics,
  };
}

type DomainDetailPageProps = {
  params: Promise<{ domainId: string }>;
  searchParams: Promise<{ tab?: string }>;
};

export default async function DomainDetailPage({
  params,
  searchParams,
}: DomainDetailPageProps) {
  const { domainId } = await params;
  const { tab = "overview" } = await searchParams;

  let domain: DomainDetail;
  try {
    const response = await serverJson<DomainDetailApiResponse>(
      ENDPOINTS.domains.detail(domainId),
    );
    domain = toDomainDetail(response);
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) {
      notFound();
    }
    throw error;
  }

  const throttle = getThrottleStatus(domainId);
  const denialEvents = getDenialEvents(domainId);

  let warmup: WarmupStatus | null = null;
  let postmaster: PostmasterData = {
    domainId,
    connected: false,
    asOf: null,
    metrics: [],
  };

  const [warmupResult, postmasterResult] = await Promise.allSettled([
    serverJson<WarmupApiResponse>(ENDPOINTS.domains.warmup(domainId)),
    serverJson<PostmasterApiResponse>(ENDPOINTS.domains.postmaster(domainId)),
  ]);

  if (warmupResult.status === "fulfilled") {
    warmup = toWarmupStatus(warmupResult.value, domainId);
  }

  if (postmasterResult.status === "fulfilled") {
    postmaster = toPostmasterData(postmasterResult.value, domainId);
  }

  const tabs = [
    { key: "overview", label: "Overview" },
    { key: "dns", label: "DNS records" },
    { key: "throughput", label: "Throughput" },
    { key: "warmup", label: "Warmup" },
    { key: "reputation", label: "Reputation" },
  ];

  return (
    <div className="page-stack">
      <header className="page-header">
        <div>
          <p className="text-sm text-text-muted">
            <Link href="/domains" className="hover:underline">
              Domains
            </Link>{" "}
            / {domain.name}
          </p>
          <h1 className="page-title">{domain.name}</h1>
        </div>
        <div className="page-actions">
          <VerifyButton domainId={domain.id} initialStatus={domain.status} />
          <DomainRetireButton domainId={domain.id} status={domain.status} />
        </div>
      </header>

      <nav aria-label="Domain detail tabs">
        <div className="flex border-b border-border">
          {tabs.map((t) => (
            <Link
              key={t.key}
              href={`/domains/${domainId}?tab=${t.key}`}
              aria-current={tab === t.key ? "page" : undefined}
              className={`inline-flex items-center border-b-2 px-3 py-2 text-sm transition-colors ${
                tab === t.key
                  ? "border-primary text-foreground"
                  : "border-transparent text-text-muted hover:text-foreground"
              }`}
            >
              {t.label}
            </Link>
          ))}
        </div>
      </nav>

      {tab === "overview" && (
        <SectionPanel title="Overview">
          <div className="summary-list">
            <div className="summary-row">
              <span className="text-sm font-medium">Status</span>
              <Badge variant={statusVariant[domain.status]}>{domain.status}</Badge>
            </div>
            <div className="summary-row">
              <span className="text-sm font-medium">Circuit breaker</span>
              <CircuitBreakerBadge
                scope="domain"
                entityId={domain.id}
                state={domain.breaker}
              />
            </div>
            {warmup && (
              <div className="summary-row">
                <span className="text-sm font-medium">Warmup</span>
                <span className="text-sm text-text-muted">
                  {warmup.currentDay === 0
                    ? "Not started"
                    : warmup.graduatedAt
                      ? "Graduated"
                      : `Day ${warmup.currentDay} / ${warmup.totalDays}`}
                </span>
              </div>
            )}
            <div className="summary-row">
              <span className="text-sm font-medium">Created</span>
              <span className="text-sm text-text-muted">
                {formatTimestamp(domain.createdAt)}
              </span>
            </div>
            <div className="summary-row">
              <span className="text-sm font-medium">Last updated</span>
              <span className="text-sm text-text-muted">
                {formatTimestamp(domain.updatedAt)}
              </span>
            </div>
          </div>
        </SectionPanel>
      )}

      {tab === "dns" && (
        <SectionPanel>
          <DnsRecords records={domain.dnsRecords} />
        </SectionPanel>
      )}

      {tab === "throughput" && (
        <SectionPanel title="Throughput">
          <ThroughputTab
            domainId={domainId}
            throttle={throttle}
            denialEvents={denialEvents}
            isAdmin={true}
          />
        </SectionPanel>
      )}

      {tab === "warmup" && (
        <SectionPanel title="Warmup schedule">
          {warmup ? (
            <WarmupTab domainId={domainId} warmup={warmup} />
          ) : (
            <p className="text-sm text-text-muted">
              No warmup schedule found for this domain.
            </p>
          )}
        </SectionPanel>
      )}

      {tab === "reputation" && (
        <SectionPanel title="Google Postmaster">
          <ReputationTab domainId={domainId} data={postmaster} />
        </SectionPanel>
      )}
    </div>
  );
}
