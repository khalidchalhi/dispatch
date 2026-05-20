import Link from "next/link";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { DataTable } from "@/components/shared/data-table";
import { formatTimestamp } from "@/lib/formatters";
import { campaigns } from "./_lib/campaigns-queries";
import type { CampaignStatus } from "@/types/campaign";

const statusVariant: Record<
  CampaignStatus,
  "muted" | "warning" | "success" | "outline" | "danger"
> = {
  draft: "muted",
  scheduled: "warning",
  running: "success",
  paused: "outline",
  completed: "outline",
  cancelled: "danger",
  failed: "danger",
};

const STATUS_TABS: { value: CampaignStatus | "all"; label: string }[] = [
  { value: "all", label: "All" },
  { value: "draft", label: "Draft" },
  { value: "scheduled", label: "Scheduled" },
  { value: "running", label: "Running" },
  { value: "paused", label: "Paused" },
  { value: "completed", label: "Completed" },
];

type CampaignsPageProps = {
  searchParams: Promise<{ status?: string }>;
};

export default async function CampaignsPage({
  searchParams,
}: CampaignsPageProps) {
  const { status } = await searchParams;
  const activeTab = (status ?? "all") as CampaignStatus | "all";

  const filtered =
    activeTab === "all"
      ? campaigns
      : campaigns.filter((c) => c.status === activeTab);

  return (
    <div className="page-stack">
      <header className="page-header">
        <div>
          <h1 className="page-title">Campaigns</h1>
          <p className="page-description">
            {campaigns.length} campaign{campaigns.length !== 1 ? "s" : ""} in
            this account.
          </p>
        </div>
        <Button asChild>
          <Link href="/campaigns/create">New campaign</Link>
        </Button>
      </header>

      {/* Status tabs */}
      <nav aria-label="Filter by status" className="flex flex-wrap gap-1">
        {STATUS_TABS.map(({ value, label }) => {
          const count =
            value === "all"
              ? campaigns.length
              : campaigns.filter((c) => c.status === value).length;
          const active = activeTab === value;
          return (
            <Link
              key={value}
              href={value === "all" ? "/campaigns" : `/campaigns?status=${value}`}
              className={`inline-flex items-center gap-1.5 rounded-md px-3 py-1.5 text-sm font-medium transition-colors ${
                active
                  ? "bg-primary primary-contrast"
                  : "bg-muted text-text-muted hover:bg-muted/80"
              }`}
              aria-current={active ? "page" : undefined}
            >
              {label}
              <span
                className={`rounded-full px-1.5 py-0.5 text-xs ${
                  active ? "bg-primary-foreground/20" : "bg-background"
                }`}
              >
                {count}
              </span>
            </Link>
          );
        })}
      </nav>

      <DataTable
        caption={`Campaigns — ${activeTab === "all" ? "all statuses" : activeTab}`}
        columns={[
          { key: "name", label: "Campaign" },
          { key: "audience", label: "Audience" },
          { key: "status", label: "Status" },
          { key: "updatedAt", label: "Updated", className: "text-right" },
        ]}
        rows={filtered.map((campaign) => ({
          name: (
            <Link
              href={`/campaigns/${campaign.id}`}
              className="font-medium hover:underline"
            >
              {campaign.name}
            </Link>
          ),
          audience: campaign.audience,
          status: (
            <Badge variant={statusVariant[campaign.status]}>
              {campaign.status}
            </Badge>
          ),
          updatedAt: (
            <span className="text-sm">{formatTimestamp(campaign.updatedAt)}</span>
          ),
        }))}
        emptyState={<span className="text-sm text-text-muted">No {activeTab === "all" ? "" : `${activeTab} `}campaigns yet.</span>}
      />
    </div>
  );
}
