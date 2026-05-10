"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import { toast } from "sonner";
import {
  CheckCircle2,
  XCircle,
  Clock,
  Loader2,
  MinusCircle,
  ChevronDown,
  ChevronRight,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { ConfirmDialog } from "@/components/shared/confirm-dialog";
import { clientJson } from "@/lib/api/client";
import { apiEndpoints } from "@/lib/api/endpoints";
import { formatTimestamp } from "@/lib/formatters";
import {
  type DomainProvisioningStatusApiResponse,
  toProvisioningAttemptFromStatus,
} from "@/app/(dashboard)/domains/_lib/provisioning-api";
import type {
  ProvisioningAttempt,
  ProvisioningStep,
  ProvisioningStepStatus,
} from "@/types/domain";

const POLL_INTERVAL_MS = 3_000;

const statusVariant: Record<
  ProvisioningStepStatus,
  "success" | "danger" | "muted" | "warning"
> = {
  success: "success",
  failed: "danger",
  running: "warning",
  pending: "muted",
  skipped: "muted",
};

function StepIcon({ status }: { status: ProvisioningStepStatus }) {
  const cls = "h-5 w-5 shrink-0";
  switch (status) {
    case "success":
      return <CheckCircle2 className={`${cls} text-success`} aria-hidden />;
    case "failed":
      return <XCircle className={`${cls} text-danger`} aria-hidden />;
    case "running":
      return (
        <Loader2 className={`${cls} text-warning animate-spin`} aria-hidden />
      );
    case "skipped":
      return (
        <MinusCircle className={`${cls} text-text-muted`} aria-hidden />
      );
    default:
      return <Clock className={`${cls} text-text-muted`} aria-hidden />;
  }
}

function formatElapsed(ms: number): string {
  if (ms < 1000) return `${ms}ms`;
  return `${(ms / 1000).toFixed(1)}s`;
}

function StepRow({ step }: { step: ProvisioningStep }) {
  const [expanded, setExpanded] = useState(false);
  const hasDiagnostic = step.status === "failed" && step.errorDetail;

  return (
    <li className="flex flex-col gap-1">
      <div className="flex items-center gap-3">
        <StepIcon status={step.status} />
        <span className="flex-1 text-sm font-medium">{step.label}</span>
        {step.elapsedMs !== null && (
          <span className="text-xs text-text-muted tabular-nums">
            {formatElapsed(step.elapsedMs)}
          </span>
        )}
        <Badge variant={statusVariant[step.status]} className="text-xs">
          {step.status}
        </Badge>
        {hasDiagnostic && (
          <button
            type="button"
            aria-expanded={expanded}
            aria-controls={`step-detail-${step.key}`}
            onClick={() => setExpanded((v) => !v)}
            className="text-text-muted hover:text-foreground"
          >
            {expanded ? (
              <ChevronDown className="h-4 w-4" aria-hidden />
            ) : (
              <ChevronRight className="h-4 w-4" aria-hidden />
            )}
          </button>
        )}
      </div>
      {hasDiagnostic && expanded && (
        <div
          id={`step-detail-${step.key}`}
          className="ml-8 rounded-md border border-danger/30 bg-danger/5 p-3 text-sm text-danger"
          role="alert"
        >
          {step.errorDetail}
        </div>
      )}
    </li>
  );
}

type StepLogProps = {
  initialAttempt: ProvisioningAttempt;
  domainId: string;
};

export function StepLog({ initialAttempt, domainId }: StepLogProps) {
  const [attempt, setAttempt] = useState<ProvisioningAttempt>(initialAttempt);
  const pollTimerRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const refreshAttempt = useCallback(async () => {
    try {
      const response = await clientJson<DomainProvisioningStatusApiResponse>(
        apiEndpoints.domains.provisioningStatus(domainId),
      );
      setAttempt((previous) =>
        toProvisioningAttemptFromStatus(
          response,
          {
            id: previous.domainId,
            name: previous.domainName,
            dns_provider: previous.provider,
          },
          previous,
        ),
      );
    } catch {
      // Keep the last rendered state on transient errors.
    }
  }, [domainId]);

  useEffect(() => {
    if (attempt.status !== "in_progress") return;

    pollTimerRef.current = setInterval(() => {
      void refreshAttempt();
    }, POLL_INTERVAL_MS);

    return () => {
      if (pollTimerRef.current) clearInterval(pollTimerRef.current);
    };
  }, [attempt.status, refreshAttempt]);

  async function handleRetry() {
    try {
      await clientJson(apiEndpoints.domains.provision(domainId), {
        method: "POST",
        body: { force: true },
      });
      toast.success("Provisioning re-enqueued.");
      await refreshAttempt();
    } catch {
      toast.error("Retry failed. Please try again.");
    }
  }

  async function handleAbandon() {
    try {
      await clientJson(apiEndpoints.domains.retire(domainId), {
        method: "POST",
      });
      toast.success("Domain abandoned and removed.");
    } catch {
      toast.error("Abandon failed. Please try again.");
    }
  }

  const overallVariant: Record<
    ProvisioningAttempt["status"],
    "success" | "danger" | "warning" | "muted"
  > = {
    completed: "success",
    failed: "danger",
    in_progress: "warning",
    abandoned: "muted",
  };

  return (
    <div className="surface-panel p-6 grid gap-6">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <Badge variant={overallVariant[attempt.status]}>
            {attempt.status.replace("_", " ")}
          </Badge>
          <span className="text-sm text-text-muted">
            Started {formatTimestamp(attempt.startedAt)}
          </span>
          {attempt.completedAt && (
            <span className="text-sm text-text-muted">
              · Finished {formatTimestamp(attempt.completedAt)}
            </span>
          )}
        </div>
      </div>

      {attempt.steps.length > 0 && (
        <ol className="grid gap-3" aria-label="Provisioning steps">
          {attempt.steps.map((step) => (
            <StepRow key={step.key} step={step} />
          ))}
        </ol>
      )}

      {attempt.status === "failed" && attempt.failureRemediation && (
        <div
          role="alert"
          className="rounded-md border border-danger/30 bg-danger/5 p-4 text-sm"
        >
          <p className="font-medium text-danger mb-1">Suggested remediation</p>
          <p className="text-foreground">{attempt.failureRemediation}</p>
        </div>
      )}

      <div className="flex items-center gap-3 pt-2 border-t border-border">
        {attempt.status === "completed" && (
          <Button asChild>
            <Link href={`/domains/${domainId}`}>View domain</Link>
          </Button>
        )}

        {attempt.status === "failed" && (
          <>
            <Button type="button" onClick={() => void handleRetry()}>
              Retry
            </Button>
            <ConfirmDialog
              title="Abandon domain"
              description="This will delete the domain record and roll back any partial provisioning. This cannot be undone."
              triggerLabel="Abandon"
              confirmLabel="Yes, abandon"
              requireReason
              reasonLabel="Reason for abandoning"
              onConfirm={() => handleAbandon()}
            />
          </>
        )}

        {attempt.status === "in_progress" && (
          <p className="text-sm text-text-muted">
            Provisioning in progress. This page updates automatically.
          </p>
        )}
      </div>
    </div>
  );
}
