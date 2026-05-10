import {
  type DomainReputation,
  type OverviewKpi,
  type TimeSeriesPoint,
  type TopCampaignRow,
} from "./_lib/analytics-queries";
import { getWarmingDomains } from "@/app/(dashboard)/domains/_lib/warmup-queries";
import { serverJson } from "@/lib/api/server";
import { apiEndpoints as ENDPOINTS } from "@/lib/api/endpoints";
import { FreshnessBanner } from "./_components/freshness-banner";
import { KpiCards } from "./_components/kpi-cards";
import { TopCampaigns } from "./_components/top-campaigns";
import { TopFailingDomains } from "./_components/top-failing-domains";
import { EngagementCharts } from "./_components/engagement-charts";
import { WarmingDomains } from "./_components/warming-domains";

const BOUNCE_WARN = 0.75;
const BOUNCE_CRITICAL = 1.5;
const COMPLAINT_WARN = 0.025;
const COMPLAINT_CRITICAL = 0.05;

type OverviewApiResponse = {
  sends_today: number;
  sends_7d: number;
  top_campaigns: Array<{
    campaign_id: string;
    name: string;
    sends_today: number;
    delivered: number;
    open_rate?: number | null;
    sparkline?: number[] | null;
  }>;
  last_updated?: string;
  last_updated_at?: string;
  bounce_rate?: number | null;
  complaint_rate?: number | null;
  open_rate?: number | null;
  click_rate?: number | null;
  time_series?: Array<{
    label: string;
    sent: number;
    delivered: number;
    bounced: number;
  }>;
  open_rate_heatmap?: number[][];
};

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
  last_updated?: string;
  last_updated_at?: string;
  items?: ReputationApiItem[];
  domains?: ReputationApiItem[];
};

function formatNumber(value: number) {
  return value.toLocaleString();
}

function formatRate(value: number | null | undefined, digits: number) {
  if (typeof value !== "number" || Number.isNaN(value)) return "—";
  return `${value.toFixed(digits)}%`;
}

function toTrend(
  trendValue: string,
  trendPositive = true,
): Pick<OverviewKpi, "trend" | "trendValue" | "trendPositive"> {
  return {
    trend: "neutral",
    trendValue,
    trendPositive,
  };
}

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

function average(values: number[]) {
  if (values.length === 0) return null;
  const sum = values.reduce((acc, value) => acc + value, 0);
  return sum / values.length;
}

function toKpis(
  overview: OverviewApiResponse,
  domains: DomainReputation[],
): OverviewKpi[] {
  const avgBounce = average(domains.map((d) => d.bounceRate));
  const avgComplaint = average(domains.map((d) => d.complaintRate));

  return [
    {
      label: "Sends today",
      value: formatNumber(overview.sends_today),
      ...toTrend("Live rollup"),
    },
    {
      label: "7-day sends",
      value: formatNumber(overview.sends_7d),
      ...toTrend("Live rollup"),
    },
    {
      label: "Bounce rate",
      value: formatRate(overview.bounce_rate ?? avgBounce, 2),
      ...toTrend("Live rollup"),
    },
    {
      label: "Complaint rate",
      value: formatRate(overview.complaint_rate ?? avgComplaint, 3),
      ...toTrend("Live rollup"),
    },
    {
      label: "Open rate",
      value: formatRate(overview.open_rate, 1),
      ...toTrend("Live rollup"),
    },
    {
      label: "Click rate",
      value: formatRate(overview.click_rate, 1),
      ...toTrend("Live rollup", false),
    },
  ];
}

function toTopCampaigns(overview: OverviewApiResponse): TopCampaignRow[] {
  return overview.top_campaigns.map((campaign) => ({
    id: campaign.campaign_id,
    name: campaign.name,
    sends: campaign.sends_today,
    openRate: campaign.open_rate ?? 0,
    sparkline:
      campaign.sparkline && campaign.sparkline.length > 0
        ? campaign.sparkline
        : [0, 0, 0, 0, 0, 0, campaign.sends_today],
  }));
}

function toTimeSeries(overview: OverviewApiResponse): TimeSeriesPoint[] {
  const series = overview.time_series ?? [];
  return series.map((point) => ({
    label: point.label,
    sent: point.sent,
    delivered: point.delivered,
    bounced: point.bounced,
  }));
}

function toHeatmap(overview: OverviewApiResponse): number[][] {
  if (overview.open_rate_heatmap && overview.open_rate_heatmap.length === 7) {
    return overview.open_rate_heatmap;
  }

  return Array.from({ length: 7 }, () => Array.from({ length: 12 }, () => 0));
}

function isStale(lastUpdatedAt: string) {
  const ageMs = Date.now() - new Date(lastUpdatedAt).getTime();
  return ageMs > 5 * 60 * 1000;
}

export default async function AnalyticsPage() {
  const [overview, reputation] = await Promise.all([
    serverJson<OverviewApiResponse>(ENDPOINTS.analytics.overview),
    serverJson<ReputationApiResponse>(ENDPOINTS.analytics.reputation),
  ]);

  const domains = toDomains(reputation);
  const kpis = toKpis(overview, domains);
  const topCampaigns = toTopCampaigns(overview);
  const timeSeries = toTimeSeries(overview);
  const heatmapCells = toHeatmap(overview);
  const warmingDomains = getWarmingDomains();
  const lastUpdatedAt =
    reputation.last_updated ??
    reputation.last_updated_at ??
    overview.last_updated ??
    overview.last_updated_at ??
    new Date().toISOString();

  return (
    <div className="page-stack">
      <header className="page-header">
        <div>
          <h1 className="page-title">Analytics</h1>
          <p className="page-description">
            Account-wide send metrics, engagement trends, and domain health.
          </p>
        </div>
      </header>

      <FreshnessBanner
        lastUpdatedAt={lastUpdatedAt}
        isStale={isStale(lastUpdatedAt)}
      />

      <KpiCards kpis={kpis} />

      <div className="grid gap-4 xl:grid-cols-2">
        <TopCampaigns rows={topCampaigns} />
        <TopFailingDomains domains={domains} />
      </div>

      <WarmingDomains domains={warmingDomains} />

      <EngagementCharts timeSeries={timeSeries} heatmapCells={heatmapCells} />
    </div>
  );
}
