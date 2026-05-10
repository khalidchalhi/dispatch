"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { toast } from "sonner";
import { ExternalLink, ShieldAlert } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { clientJson } from "@/lib/api/client";
import { apiEndpoints } from "@/lib/api/endpoints";
import { formatTimestamp } from "@/lib/formatters";
import type { PostmasterData, PostmasterReputation } from "@/types/domain";

const reputationVariant: Record<
  PostmasterReputation,
  "success" | "warning" | "danger" | "muted"
> = {
  high: "success",
  medium: "warning",
  low: "danger",
  bad: "danger",
};

function MetricCard({
  label,
  value,
  sub,
}: {
  label: string;
  value: string;
  sub?: string;
}) {
  return (
    <div className="surface-panel p-4">
      <p className="text-xs font-medium uppercase tracking-wide text-text-muted">
        {label}
      </p>
      <p className="mt-2 text-xl font-semibold tabular-nums">{value}</p>
      {sub && <p className="mt-0.5 text-xs text-text-muted">{sub}</p>}
    </div>
  );
}

type ReputationTabProps = {
  domainId: string;
  data: PostmasterData;
};

export function ReputationTab({ domainId, data }: ReputationTabProps) {
  const router = useRouter();
  const [connecting, setConnecting] = useState(false);

  async function handleConnect() {
    setConnecting(true);
    try {
      const response = await clientJson<{
        authorization_url?: string;
        oauth_url?: string;
        redirect_url?: string;
      }>(apiEndpoints.domains.postmasterConnect(domainId), {
        method: "POST",
      });

      const oauthUrl =
        response.authorization_url ?? response.oauth_url ?? response.redirect_url;

      if (typeof oauthUrl === "string" && oauthUrl.length > 0) {
        window.location.assign(oauthUrl);
        return;
      }

      toast.success("Postmaster connection initiated.");
      router.refresh();
    } catch {
      toast.error("Failed to initiate connection. Please try again.");
    } finally {
      setConnecting(false);
    }
  }

  if (!data.connected) {
    return (
      <div className="grid gap-4">
        <div className="flex items-start gap-3 rounded-md border border-border p-5">
          <ShieldAlert className="mt-0.5 h-5 w-5 shrink-0 text-text-muted" aria-hidden />
          <div className="grid gap-2">
            <p className="font-medium">Google Postmaster not connected</p>
            <p className="text-sm text-text-muted">
              Connect your Google Postmaster Tools account to surface inbox reputation
              signals — spam rate, domain reputation, and authentication pass rates —
              directly alongside your dispatch metrics.
            </p>
            <div className="flex items-center gap-3 pt-1">
              <Button
                size="sm"
                disabled={connecting}
                onClick={() => void handleConnect()}
              >
                {connecting ? "Connecting…" : "Connect Postmaster"}
              </Button>
              <a
                href="https://postmaster.google.com"
                target="_blank"
                rel="noopener noreferrer"
                className="inline-flex items-center gap-1 text-sm text-text-muted hover:underline"
              >
                Open Postmaster
                <ExternalLink className="h-3 w-3" aria-hidden />
              </a>
            </div>
          </div>
        </div>
      </div>
    );
  }

  const latest = data.metrics.at(-1);

  return (
    <div className="grid gap-6">
      {/* Header: as-of timestamp + external link */}
      <div className="flex items-center justify-between">
        <p className="text-sm text-text-muted">
          As of{" "}
          <span className="font-medium text-foreground">
            {data.asOf ? formatTimestamp(data.asOf) : "—"}
          </span>
        </p>
        <a
          href="https://postmaster.google.com"
          target="_blank"
          rel="noopener noreferrer"
          className="inline-flex items-center gap-1 text-sm text-text-muted hover:underline"
        >
          Open Postmaster
          <ExternalLink className="h-3.5 w-3.5" aria-hidden />
        </a>
      </div>

      {/* Latest metric cards */}
      {latest && (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          <MetricCard
            label="Spam rate"
            value={`${latest.spamRatePct.toFixed(2)}%`}
            sub="Google-reported"
          />
          <div className="surface-panel p-4">
            <p className="text-xs font-medium uppercase tracking-wide text-text-muted">
              Domain reputation
            </p>
            <div className="mt-2">
              <Badge variant={reputationVariant[latest.domainReputation]}>
                {latest.domainReputation}
              </Badge>
            </div>
          </div>
          <MetricCard
            label="SPF pass"
            value={`${latest.spfPassPct.toFixed(1)}%`}
            sub="Last 24h"
          />
          <MetricCard
            label="DKIM pass"
            value={`${latest.dkimPassPct.toFixed(1)}%`}
            sub="Last 24h"
          />
        </div>
      )}

      {/* 7-day metrics table */}
      {data.metrics.length > 0 && (
        <div>
          <p className="mb-2 text-sm font-medium">Last 7 days</p>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-border text-left text-text-muted">
                  <th className="pb-2 pr-6 font-medium">Date</th>
                  <th className="pb-2 pr-6 font-medium">Spam rate</th>
                  <th className="pb-2 pr-6 font-medium">Reputation</th>
                  <th className="pb-2 pr-6 font-medium">SPF pass</th>
                  <th className="pb-2 pr-6 font-medium">DKIM pass</th>
                  <th className="pb-2 font-medium">DMARC pass</th>
                </tr>
              </thead>
              <tbody>
                {[...data.metrics].reverse().map((m) => (
                  <tr key={m.date} className="border-b border-border/50">
                    <td className="py-2 pr-6 tabular-nums text-text-muted">
                      {m.date}
                    </td>
                    <td className="py-2 pr-6 tabular-nums">
                      {m.spamRatePct.toFixed(2)}%
                    </td>
                    <td className="py-2 pr-6">
                      <Badge variant={reputationVariant[m.domainReputation]}>
                        {m.domainReputation}
                      </Badge>
                    </td>
                    <td className="py-2 pr-6 tabular-nums">
                      {m.spfPassPct.toFixed(1)}%
                    </td>
                    <td className="py-2 pr-6 tabular-nums">
                      {m.dkimPassPct.toFixed(1)}%
                    </td>
                    <td className="py-2 tabular-nums">
                      {m.dmarcPassPct.toFixed(1)}%
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}
