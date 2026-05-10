import Link from "next/link";
import { Badge } from "@/components/ui/badge";
import { serverJson } from "@/lib/api/server";
import { apiEndpoints as ENDPOINTS } from "@/lib/api/endpoints";
import { FreshnessBanner } from "../_components/freshness-banner";
import type { DomainReputation, RiskLevel } from "../_lib/analytics-queries";

const riskVariant: Record<RiskLevel, "success" | "warning" | "danger"> = {
  ok: "success",
  warn: "warning",
  critical: "danger",
};

const breakerVariant: Record<
  DomainReputation["breakerState"],
  "success" | "danger" | "warning"
> = {
  closed: "success",
  open: "danger",
  "half-open": "warning",
};

// Thresholds for color-coded cell rendering
function rateColor(value: number, warn: number, critical: number) {
  if (value >= critical) return "text-danger font-semibold";
  if (value >= warn) return "text-warning font-medium";
  return "text-foreground";
}

const BOUNCE_WARN = 0.75;
const BOUNCE_CRITICAL = 1.5;
const COMPLAINT_WARN = 0.025;
const COMPLAINT_CRITICAL = 0.05;

type ReputationApiItem = {
  domain_id?: string;
  id?: string;
  domain_name?: string;
  name?: string;
  bounce_rate?: number | null;
  bounceRate?: number | null;
  complaint_rate?: number | null;
  complaintRate?: number | null;
  delivery_rate?: number | null;
  deliveryRate?: number | null;
  circuit_breaker_state?: string | null;
  breaker_state?: string | null;
  breakerState?: string | null;
  warmup_stage?: string | null;
  warmupStage?: string | null;
  risk_level?: string | null;
  riskLevel?: string | null;
};

type ReputationApiResponse = {
  last_updated_at?: string;
  items?: ReputationApiItem[];
  domains?: ReputationApiItem[];
};

function toRiskLevel(
  bounceRate: number,
  complaintRate: number,
): DomainReputation["riskLevel"] {
  if (bounceRate >= BOUNCE_CRITICAL || complaintRate >= COMPLAINT_CRITICAL) {
    return "critical";
  }
  if (bounceRate >= BOUNCE_WARN || complaintRate >= COMPLAINT_WARN) {
    return "warn";
  }
  return "ok";
}

function toBreakerState(value: string | null | undefined): DomainReputation["breakerState"] {
  if (value === "open") return "open";
  if (value === "half-open") return "half-open";
  return "closed";
}

function toDomains(response: ReputationApiResponse): DomainReputation[] {
  const rows = response.items ?? response.domains ?? [];
  return rows.map((item, index) => {
    const bounceRate = item.bounce_rate ?? item.bounceRate ?? 0;
    const complaintRate = item.complaint_rate ?? item.complaintRate ?? 0;
    const deliveryRate = item.delivery_rate ?? item.deliveryRate ?? 0;

    const riskRaw = item.risk_level ?? item.riskLevel;
    const riskLevel: DomainReputation["riskLevel"] =
      riskRaw === "ok" || riskRaw === "warn" || riskRaw === "critical"
        ? riskRaw
        : toRiskLevel(bounceRate, complaintRate);

    const breakerRaw =
      item.circuit_breaker_state ?? item.breaker_state ?? item.breakerState;

    return {
      id: item.domain_id ?? item.id ?? `domain-${index}`,
      name: item.domain_name ?? item.name ?? "Unknown domain",
      bounceRate,
      complaintRate,
      deliveryRate,
      breakerState: toBreakerState(breakerRaw),
      warmupStage: item.warmup_stage ?? item.warmupStage ?? "Unknown",
      riskLevel,
    };
  });
}

function isStale(lastUpdatedAt: string) {
  const ageMs = Date.now() - new Date(lastUpdatedAt).getTime();
  return ageMs > 5 * 60 * 1000;
}

export default async function ReputationPage() {
  const response = await serverJson<ReputationApiResponse>(
    ENDPOINTS.analytics.reputation,
  );
  const domains = toDomains(response);
  const lastUpdatedAt = response.last_updated_at ?? new Date().toISOString();

  return (
    <div className="page-stack">
      <header className="page-header">
        <div>
          <h1 className="page-title">Domain reputation</h1>
          <p className="page-description">
            Per-domain send health. Warn at 50% of circuit-breaker threshold;
            critical at 100%.
          </p>
        </div>
      </header>

      <FreshnessBanner
        lastUpdatedAt={lastUpdatedAt}
        isStale={isStale(lastUpdatedAt)}
      />

      {/* Threshold legend */}
      <div className="surface-panel p-4 flex flex-wrap gap-6 text-xs text-text-muted">
        <span>
          Bounce warn ≥{" "}
          <span className="text-warning font-medium">0.75%</span> · critical ≥{" "}
          <span className="text-danger font-semibold">1.5%</span>
        </span>
        <span>
          Complaint warn ≥{" "}
          <span className="text-warning font-medium">0.025%</span> · critical ≥{" "}
          <span className="text-danger font-semibold">0.05%</span>
        </span>
      </div>

      <div className="surface-panel overflow-x-auto">
        <table className="w-full text-sm">
          <caption className="sr-only">Domain reputation metrics</caption>
          <thead>
            <tr className="border-b border-border text-left">
              <th className="px-4 py-3 font-medium text-text-muted">Domain</th>
              <th className="px-4 py-3 font-medium text-text-muted text-right">
                Bounce%
              </th>
              <th className="px-4 py-3 font-medium text-text-muted text-right">
                Complaint%
              </th>
              <th className="px-4 py-3 font-medium text-text-muted text-right">
                Delivery%
              </th>
              <th className="px-4 py-3 font-medium text-text-muted">Breaker</th>
              <th className="px-4 py-3 font-medium text-text-muted">
                Warmup stage
              </th>
              <th className="px-4 py-3 font-medium text-text-muted">Risk</th>
            </tr>
          </thead>
          <tbody>
            {domains.map((domain) => (
              <tr
                key={domain.id}
                className="border-b border-border/50 hover:bg-surface-muted transition-colors"
              >
                <td className="px-4 py-3">
                  <Link
                    href={`/domains/${domain.id}`}
                    className="mono text-sm font-medium hover:underline"
                  >
                    {domain.name}
                  </Link>
                </td>
                <td
                  className={`px-4 py-3 mono text-right tabular-nums ${rateColor(domain.bounceRate, 0.75, 1.5)}`}
                >
                  {domain.bounceRate > 0
                    ? `${domain.bounceRate.toFixed(2)}%`
                    : "—"}
                </td>
                <td
                  className={`px-4 py-3 mono text-right tabular-nums ${rateColor(domain.complaintRate, 0.025, 0.05)}`}
                >
                  {domain.complaintRate > 0
                    ? `${domain.complaintRate.toFixed(3)}%`
                    : "—"}
                </td>
                <td className="px-4 py-3 mono text-right tabular-nums">
                  {domain.deliveryRate > 0
                    ? `${domain.deliveryRate.toFixed(1)}%`
                    : "—"}
                </td>
                <td className="px-4 py-3">
                  <Badge variant={breakerVariant[domain.breakerState]}>
                    {domain.breakerState}
                  </Badge>
                </td>
                <td className="px-4 py-3 text-text-muted">
                  {domain.warmupStage}
                </td>
                <td className="px-4 py-3">
                  <Badge variant={riskVariant[domain.riskLevel]}>
                    {domain.riskLevel}
                  </Badge>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
