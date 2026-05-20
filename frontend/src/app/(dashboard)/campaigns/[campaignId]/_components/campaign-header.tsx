"use client";

import { toast } from "sonner";
import { Badge } from "@/components/ui/badge";
import { ConfirmDialog } from "@/components/shared/confirm-dialog";
import { CircuitBreakerBadge } from "@/components/shared/circuit-breaker-badge";
import { clientJson } from "@/lib/api/client";
import { apiEndpoints } from "@/lib/api/endpoints";
import type { CampaignDetail, CampaignKpis, CampaignStatus } from "@/types/campaign";
import type { BreakerEntryState } from "@/types/ops";

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

type KpiTileProps = { label: string; value: number };

function KpiTile({ label, value }: KpiTileProps) {
  return (
    <div className="surface-panel-muted rounded-lg p-4 text-center">
      <p className="mono text-xl font-semibold tabular-nums">
        {value.toLocaleString()}
      </p>
      <p className="mt-0.5 text-xs text-text-muted">{label}</p>
    </div>
  );
}

const KPI_KEYS: { key: keyof CampaignKpis; label: string }[] = [
  { key: "queued", label: "Queued" },
  { key: "sending", label: "Sending" },
  { key: "sent", label: "Sent" },
  { key: "delivered", label: "Delivered" },
  { key: "bounced", label: "Bounced" },
  { key: "complained", label: "Complained" },
  { key: "opened", label: "Opened" },
  { key: "clicked", label: "Clicked" },
];

type CampaignHeaderProps = {
  detail: CampaignDetail;
  onStatusChange: (newStatus: CampaignStatus) => void;
  domainBreakerState?: BreakerEntryState;
  domainId?: string;
};

export function CampaignHeader({
  detail,
  onStatusChange,
  domainBreakerState,
  domainId,
}: CampaignHeaderProps) {
  const { status } = detail;

  async function handleAction(action: "pause" | "resume" | "cancel") {
    try {
      await clientJson(apiEndpoints.campaigns[action](detail.id), {
        method: "POST",
      });
      const next: CampaignStatus =
        action === "pause" ? "paused" : action === "resume" ? "running" : "cancelled";
      onStatusChange(next);
      toast.success(
        action === "pause"
          ? "Campaign paused."
          : action === "resume"
            ? "Campaign resumed."
            : "Campaign cancelled.",
      );
    } catch {
      toast.error("Action failed. Please retry.");
    }
  }

  return (
    <section className="surface-panel p-6 grid gap-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="section-title">{detail.name}</h2>
          <p className="page-description">{detail.audience}</p>
        </div>
        <div className="flex items-center gap-2 flex-wrap">
          <Badge variant={statusVariant[status]}>{status}</Badge>

          {domainBreakerState && domainId && (
            <CircuitBreakerBadge
              scope="domain"
              entityId={domainId}
              state={domainBreakerState}
            />
          )}

          {status === "running" && (
            <ConfirmDialog
              title="Pause campaign"
              description="Pausing will stop new sends from being dispatched. In-flight messages continue. You can resume at any time."
              triggerLabel="Pause"
              confirmLabel="Pause campaign"
              onConfirm={() => handleAction("pause")}
            />
          )}

          {status === "paused" && (
            <ConfirmDialog
              title="Resume campaign"
              description="Resuming will re-enter queued messages into the send pipeline."
              triggerLabel="Resume"
              confirmLabel="Resume campaign"
              onConfirm={() => handleAction("resume")}
            />
          )}

          {(status === "running" || status === "paused") && (
            <ConfirmDialog
              title="Cancel campaign"
              description="Cancelling permanently stops all remaining sends. This cannot be undone."
              triggerLabel="Cancel"
              confirmLabel="Cancel campaign"
              requireReason
              reasonLabel="Cancellation reason"
              onConfirm={() => handleAction("cancel")}
            />
          )}
        </div>
      </div>

      <div
        aria-label="Campaign KPI tiles"
        className="grid grid-cols-2 gap-3 sm:grid-cols-4 lg:grid-cols-8"
      >
        {KPI_KEYS.map(({ key, label }) => (
          <KpiTile key={key} label={label} value={detail.kpis[key]} />
        ))}
      </div>

      <div className="summary-list">
        <div className="summary-row">
          <span className="text-sm font-medium">Campaign ID</span>
          <span className="mono text-sm text-text-muted">{detail.id}</span>
        </div>
        <div className="summary-row">
          <span className="text-sm font-medium">Last updated</span>
          <span className="text-sm text-text-muted">{detail.updatedAt}</span>
        </div>
      </div>
    </section>
  );
}
