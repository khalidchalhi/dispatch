"use client";

import { useEffect, useState } from "react";
import { clientJson } from "@/lib/api/client";
import { apiEndpoints } from "@/lib/api/endpoints";
import { formatTimestamp } from "@/lib/formatters";
import type { ImportJob } from "@/types/import";
import { toImportJob, type ApiImportJobResponse } from "../_lib/import-api";

const POLL_INTERVAL_MS = 2_000;

type ProgressStepProps = {
  jobId: string;
  fileName: string;
  onComplete: (job: ImportJob) => void;
};

export function ProgressStep({ jobId, fileName, onComplete }: ProgressStepProps) {
  const [job, setJob] = useState<ImportJob | null>(null);
  const [pollError, setPollError] = useState(false);

  useEffect(() => {
    let cancelled = false;
    let timeoutId: ReturnType<typeof setTimeout> | null = null;

    async function poll() {
      if (cancelled) return;
      try {
        const result = await clientJson<ApiImportJobResponse>(
          apiEndpoints.contacts.importJobStatus(jobId),
        );
        const mapped = toImportJob(result);
        if (!cancelled) {
          setJob(mapped);
          setPollError(false);
          if (mapped.status === "completed" || mapped.status === "failed") {
            onComplete(mapped);
            return;
          }
          timeoutId = setTimeout(() => void poll(), POLL_INTERVAL_MS);
        }
      } catch {
        if (!cancelled) {
          setPollError(true);
          timeoutId = setTimeout(() => void poll(), POLL_INTERVAL_MS);
        }
      }
    }

    void poll();
    return () => {
      cancelled = true;
      if (timeoutId) clearTimeout(timeoutId);
    };
  }, [jobId, onComplete]);

  const progressPct =
    job && job.totalRows > 0
      ? Math.round((job.processedRows / job.totalRows) * 100)
      : 0;

  return (
    <div className="grid gap-6">
      <div className="surface-panel p-6">
        <div className="mb-4 flex items-start justify-between gap-3">
          <div>
            <p className="font-medium">{fileName}</p>
            <p className="text-sm text-text-muted">
              {job
                ? `${job.processedRows.toLocaleString()} of ${job.totalRows.toLocaleString()} rows processed`
                : "Waiting for job to start…"}
            </p>
          </div>
          {job ? (
            <span
              className={`text-sm font-medium ${
                job.status === "failed" ? "text-danger" : "text-text-muted"
              }`}
            >
              {job.status}
            </span>
          ) : null}
        </div>

        <div
          role="progressbar"
          aria-label="Import progress"
          aria-valuenow={progressPct}
          aria-valuemin={0}
          aria-valuemax={100}
          className="h-2 w-full overflow-hidden rounded-full bg-surface-muted"
        >
          <div
            className="h-full rounded-full bg-primary transition-all duration-500"
            style={{ width: `${progressPct}%` }}
          />
        </div>

        {job ? (
          <dl className="mt-4 grid grid-cols-2 gap-3 sm:grid-cols-4">
            <div className="surface-panel-muted rounded-lg p-3 text-center">
              <dd className="text-lg font-semibold">
                {job.acceptedRows.toLocaleString()}
              </dd>
              <dt className="text-xs text-text-muted">Accepted</dt>
            </div>
            <div className="surface-panel-muted rounded-lg p-3 text-center">
              <dd className="text-lg font-semibold text-danger">
                {job.rejectedRows.toLocaleString()}
              </dd>
              <dt className="text-xs text-text-muted">Rejected</dt>
            </div>
            <div className="surface-panel-muted rounded-lg p-3 text-center">
              <dd className="text-lg font-semibold text-text-muted">
                {job.duplicateRows.toLocaleString()}
              </dd>
              <dt className="text-xs text-text-muted">Duplicates</dt>
            </div>
            <div className="surface-panel-muted rounded-lg p-3 text-center">
              <dd className="text-lg font-semibold">
                {job.totalRows.toLocaleString()}
              </dd>
              <dt className="text-xs text-text-muted">Total</dt>
            </div>
          </dl>
        ) : null}
      </div>

      {pollError ? (
        <p className="text-sm text-text-muted">
          Lost connection to the server. Retrying in 2 seconds…
        </p>
      ) : null}

      {job?.status === "completed" ? (
        <div className="surface-panel-muted rounded-lg p-4">
          <p className="font-medium">Import complete</p>
          <p className="mt-1 text-sm text-text-muted">
            Finished {job.completedAt ? formatTimestamp(job.completedAt) : ""}.
            {job.rejectedRows > 0
              ? ` ${job.rejectedRows.toLocaleString()} row(s) were rejected — review them below.`
              : " All rows were accepted."}
          </p>
        </div>
      ) : null}

      {job?.status === "failed" ? (
        <div className="rounded-lg border border-danger/30 bg-[color:var(--danger-bg)] p-4">
          <p className="font-medium text-danger">Import failed</p>
          <p className="mt-1 text-sm text-text-muted">
            The job encountered a fatal error. Contact support if this persists.
          </p>
        </div>
      ) : null}
    </div>
  );
}
