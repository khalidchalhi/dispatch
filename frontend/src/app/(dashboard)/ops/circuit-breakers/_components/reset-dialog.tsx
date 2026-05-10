"use client";

import { useState } from "react";
import { toast } from "sonner";
import { AlertTriangle } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { clientJson } from "@/lib/api/client";
import { formatTimestamp } from "@/lib/formatters";
import type { BreakerEntry } from "@/types/ops";

const reasonLabel: Record<string, string> = {
  high_bounce_rate: "High bounce rate",
  high_complaint_rate: "High complaint rate",
};

type ResetDialogProps = {
  entry: BreakerEntry | null;
  onClose: () => void;
  onReset: (breakerId: string) => void | Promise<void>;
};

export function ResetDialog({ entry, onClose, onReset }: ResetDialogProps) {
  const [justification, setJustification] = useState("");
  const [accountConfirmed, setAccountConfirmed] = useState(false);
  const [isSaving, setIsSaving] = useState(false);

  const isAccount = entry?.scope === "account";
  const justificationValid = justification.trim().length >= 10;
  const canSubmit =
    justificationValid && (!isAccount || accountConfirmed) && !isSaving;

  function handleOpenChange(open: boolean) {
    if (!open) {
      setJustification("");
      setAccountConfirmed(false);
      onClose();
    }
  }

  async function handleReset() {
    if (!entry || !canSubmit) return;
    setIsSaving(true);
    try {
      await clientJson(`/api/circuit-breakers/${entry.id}/reset`, {
        method: "POST",
        body: { justification: justification.trim() },
      });
      toast.success(`Circuit breaker reset for ${entry.entityName}`);
      await onReset(entry.id);
      handleOpenChange(false);
    } catch {
      toast.error("Reset failed. Please retry.");
    } finally {
      setIsSaving(false);
    }
  }

  return (
    <Dialog open={entry !== null} onOpenChange={handleOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Reset circuit breaker</DialogTitle>
          <DialogDescription>
            {entry
              ? `Resetting the breaker for ${entry.entityName} will resume sends through this ${entry.scope.replace("_", " ")}.`
              : ""}
          </DialogDescription>
        </DialogHeader>

        {entry && (
          <div className="grid gap-4">
            <div className="surface-panel-muted grid gap-2 rounded-md p-3 text-sm">
              <div className="flex justify-between">
                <span className="text-text-muted">Scope</span>
                <span className="font-medium capitalize">
                  {entry.scope.replace("_", " ")}
                </span>
              </div>
              <div className="flex justify-between">
                <span className="text-text-muted">Tripped at</span>
                <span>
                  {entry.trippedAt ? formatTimestamp(entry.trippedAt) : "—"}
                </span>
              </div>
              <div className="flex justify-between">
                <span className="text-text-muted">Reason</span>
                <span className="text-warning font-medium">
                  {entry.reason ? (reasonLabel[entry.reason] ?? entry.reason) : "—"}
                </span>
              </div>
              {entry.bounceRatePct !== null && (
                <div className="flex justify-between">
                  <span className="text-text-muted">Bounce rate</span>
                  <span>{entry.bounceRatePct.toFixed(2)}%</span>
                </div>
              )}
              {entry.complaintRatePct !== null && (
                <div className="flex justify-between">
                  <span className="text-text-muted">Complaint rate</span>
                  <span>{entry.complaintRatePct.toFixed(3)}%</span>
                </div>
              )}
            </div>

            <div className="grid gap-1.5">
              <label htmlFor="reset-justification" className="text-sm font-medium">
                Justification{" "}
                <span className="text-text-muted font-normal">(min 10 chars)</span>
              </label>
              <textarea
                id="reset-justification"
                rows={3}
                className="rounded-md border border-border bg-background px-3 py-2 text-sm placeholder:text-text-muted focus:outline-none focus:ring-2 focus:ring-[color:var(--focus-ring)] resize-none"
                placeholder="Describe what was investigated and why it is safe to resume."
                value={justification}
                onChange={(e) => setJustification(e.target.value)}
              />
              {justification.length > 0 && !justificationValid && (
                <p className="text-xs text-danger">
                  At least 10 characters required.
                </p>
              )}
            </div>

            {isAccount && (
              <div
                role="alert"
                className="flex items-start gap-3 rounded-md border border-danger/40 bg-danger/10 p-3"
              >
                <AlertTriangle
                  className="mt-0.5 h-4 w-4 shrink-0 text-danger"
                  aria-hidden
                />
                <div className="grid gap-2">
                  <p className="text-sm font-medium text-danger">
                    Account-scope reset
                  </p>
                  <p className="text-sm">
                    This breaker pauses <strong>all sends</strong> across the
                    platform. Confirm only after verifying account-level metrics
                    are clean.
                  </p>
                  <label className="flex items-center gap-2 text-sm">
                    <input
                      type="checkbox"
                      checked={accountConfirmed}
                      onChange={(e) => setAccountConfirmed(e.target.checked)}
                      aria-label="I understand this affects all sends"
                    />
                    I understand this will resume all platform sends
                  </label>
                </div>
              </div>
            )}
          </div>
        )}

        <DialogFooter>
          <Button type="button" variant="outline" onClick={() => handleOpenChange(false)}>
            Cancel
          </Button>
          <Button
            type="button"
            disabled={!canSubmit}
            onClick={() => void handleReset()}
          >
            {isSaving ? "Resetting…" : "Reset breaker"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
