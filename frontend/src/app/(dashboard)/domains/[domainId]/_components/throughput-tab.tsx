"use client";

import { useState } from "react";
import { toast } from "sonner";
import { AlertTriangle } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { formatTimestamp } from "@/lib/formatters";
import { clientJson } from "@/lib/api/client";
import type { DenialEvent, ThrottleStatus } from "@/types/domain";

const reasonLabel: Record<string, string> = {
  token_bucket_empty: "Token bucket empty",
  rate_limit_exceeded: "Rate limit exceeded",
  circuit_breaker_open: "Circuit breaker open",
};

type ThroughputTabProps = {
  domainId: string;
  throttle: ThrottleStatus;
  denialEvents: DenialEvent[];
  isAdmin: boolean;
};

export function ThroughputTab({
  domainId,
  throttle,
  denialEvents,
  isAdmin,
}: ThroughputTabProps) {
  const [rateLimit, setRateLimit] = useState(throttle.rateLimit);
  const [editValue, setEditValue] = useState(String(throttle.rateLimit));
  const [confirmPending, setConfirmPending] = useState(false);
  const [isSaving, setIsSaving] = useState(false);

  const parsed = parseInt(editValue, 10);
  const isValid = !isNaN(parsed) && parsed > 0;
  const isDrastic = isValid && parsed < rateLimit * 0.5;
  const isChanged = isValid && parsed !== rateLimit;

  async function save(value: number) {
    setIsSaving(true);
    try {
      await clientJson(`/api/domains/${domainId}/throttle`, {
        method: "POST",
        body: { rateLimit: value },
      });
      setRateLimit(value);
      setConfirmPending(false);
      toast.success(`Rate limit updated to ${value.toLocaleString()} sends/hr`);
    } catch {
      toast.error("Failed to update rate limit");
    } finally {
      setIsSaving(false);
    }
  }

  function handleSave() {
    if (!isValid) {
      toast.error("Enter a positive number");
      return;
    }
    if (isDrastic && !confirmPending) {
      setConfirmPending(true);
      return;
    }
    void save(parsed);
  }

  const tokenPct = Math.round((throttle.tokensAvailable / rateLimit) * 100);

  return (
    <div className="grid gap-6">
      <section aria-label="Token bucket status">
        <h2 className="section-title mb-4">Token bucket</h2>
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
          <div className="surface-panel-muted flex flex-col gap-1 p-4">
            <span className="text-xs text-text-muted">Rate limit</span>
            <span className="text-lg font-semibold tabular-nums">
              {rateLimit.toLocaleString()}
            </span>
            <span className="text-xs text-text-muted">sends / hr</span>
          </div>
          <div className="surface-panel-muted flex flex-col gap-1 p-4">
            <span className="text-xs text-text-muted">Tokens available</span>
            <span className="text-lg font-semibold tabular-nums">
              {throttle.tokensAvailable.toLocaleString()}
            </span>
            <span className="text-xs text-text-muted">{tokenPct}% full</span>
          </div>
          <div className="surface-panel-muted flex flex-col gap-1 p-4">
            <span className="text-xs text-text-muted">Refill rate</span>
            <span className="text-lg font-semibold tabular-nums">
              {throttle.refillRate.toFixed(1)}
            </span>
            <span className="text-xs text-text-muted">tokens / min</span>
          </div>
          <div className="surface-panel-muted flex flex-col gap-1 p-4">
            <span className="text-xs text-text-muted">Denials / min</span>
            <span
              className={`text-lg font-semibold tabular-nums ${throttle.denialsPerMinute > 0 ? "text-warning" : ""}`}
            >
              {throttle.denialsPerMinute.toFixed(1)}
            </span>
            <span className="text-xs text-text-muted">
              {formatTimestamp(throttle.updatedAt)}
            </span>
          </div>
        </div>
      </section>

      {isAdmin && (
        <section aria-label="Edit rate limit">
          <h2 className="section-title mb-4">Edit rate limit</h2>
          <div className="surface-panel-muted max-w-sm p-4">
            <div className="flex items-end gap-3">
              <div className="flex flex-1 flex-col gap-1">
                <label
                  htmlFor="rate-limit-input"
                  className="text-sm font-medium"
                >
                  Sends per hour
                </label>
                <input
                  id="rate-limit-input"
                  type="number"
                  min={1}
                  className="input-base h-9 w-full rounded-md border border-border bg-background px-3 py-1 text-sm"
                  value={editValue}
                  onChange={(e) => {
                    setEditValue(e.target.value);
                    setConfirmPending(false);
                  }}
                  aria-describedby={confirmPending ? "rate-limit-warning" : undefined}
                />
              </div>
              <Button
                type="button"
                size="sm"
                disabled={!isChanged || isSaving}
                onClick={handleSave}
              >
                {isSaving ? "Saving…" : confirmPending ? "Confirm" : "Save"}
              </Button>
            </div>

            {confirmPending && (
              <div
                id="rate-limit-warning"
                role="alert"
                className="mt-3 flex items-start gap-2 rounded-md border border-warning/40 bg-warning/10 p-3"
              >
                <AlertTriangle
                  className="mt-0.5 h-4 w-4 shrink-0 text-warning"
                  aria-hidden
                />
                <p className="text-sm text-warning">
                  This reduces the rate limit by more than 50%. Confirm to
                  apply.
                </p>
              </div>
            )}
          </div>
        </section>
      )}

      <section aria-label="Recent denial events">
        <h2 className="section-title mb-4">Recent denial events</h2>
        {denialEvents.length === 0 ? (
          <p className="text-sm text-text-muted">No denial events recorded.</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-border text-left text-text-muted">
                  <th className="pb-2 pr-6 font-medium">Occurred</th>
                  <th className="pb-2 pr-6 font-medium">Reason</th>
                  <th className="pb-2 text-right font-medium">Recipients</th>
                </tr>
              </thead>
              <tbody>
                {denialEvents.map((ev) => (
                  <tr key={ev.id} className="border-b border-border/50">
                    <td className="py-2 pr-6 text-text-muted">
                      {formatTimestamp(ev.occurredAt)}
                    </td>
                    <td className="py-2 pr-6">
                      <Badge variant="warning">
                        {reasonLabel[ev.reason] ?? ev.reason}
                      </Badge>
                    </td>
                    <td className="py-2 text-right tabular-nums">
                      {ev.recipientCount.toLocaleString()}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </div>
  );
}
