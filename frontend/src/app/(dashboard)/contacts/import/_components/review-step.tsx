"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { Button } from "@/components/ui/button";
import { DataTable } from "@/components/shared/data-table";
import { clientJson } from "@/lib/api/client";
import { apiEndpoints } from "@/lib/api/endpoints";
import type { ImportJob } from "@/types/import";
import type { ApiImportErrorRowResponse } from "../_lib/import-api";

type ImportErrorRowView = {
  rowNumber: number;
  column: string;
  errorMessage: string;
};

function inferColumn(reason: string | null): string {
  if (reason?.startsWith("gate") || reason === "duplicate_in_file") {
    return "email";
  }
  return "unknown";
}

function toErrorMessage(reason: string | null): string {
  if (reason === "gate1_invalid_format") return "Invalid email format";
  if (reason === "gate1_disposable_domain") return "Disposable domain";
  if (reason === "gate2_no_mx") return "No MX records for domain";
  if (reason === "gate2_smtp_probe_failed") return "SMTP validation failed";
  if (reason === "gate3_role_account") return "Role-based email is blocked";
  if (reason === "duplicate_in_file") return "Duplicate email in CSV";
  if (!reason) return "Validation error";
  return reason.replaceAll("_", " ");
}

function toImportErrorRowView(api: ApiImportErrorRowResponse): ImportErrorRowView {
  return {
    rowNumber: api.row_number,
    column: inferColumn(api.error_reason),
    errorMessage: toErrorMessage(api.error_reason),
  };
}

function exportErrorsCSV(errors: ImportErrorRowView[], fileName: string) {
  const header = "row,column,error_message\n";
  const rows = errors
    .map(
      (e) =>
        `${e.rowNumber},"${e.column}","${e.errorMessage.replace(/"/g, '""')}"`,
    )
    .join("\n");
  const blob = new Blob([header + rows], { type: "text/csv" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `import-errors-${fileName.replace(/\.csv$/, "")}.csv`;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}

type ReviewStepProps = {
  job: ImportJob;
};

export function ReviewStep({ job }: ReviewStepProps) {
  const [errors, setErrors] = useState<ImportErrorRowView[]>([]);
  const [loading, setLoading] = useState(true);
  const [fetchError, setFetchError] = useState(false);

  useEffect(() => {
    async function load() {
      try {
        const result = await clientJson<ApiImportErrorRowResponse[]>(
          apiEndpoints.contacts.importJobErrors(job.id),
        );
        setErrors(result.map(toImportErrorRowView));
      } catch {
        setFetchError(true);
      } finally {
        setLoading(false);
      }
    }
    void load();
  }, [job.id]);

  return (
    <div className="grid gap-6">
      <div className="surface-panel-muted grid grid-cols-2 gap-3 rounded-lg p-4 sm:grid-cols-4">
        <div className="text-center">
          <p className="text-lg font-semibold">
            {job.acceptedRows.toLocaleString()}
          </p>
          <p className="text-xs text-text-muted">Accepted</p>
        </div>
        <div className="text-center">
          <p className="text-lg font-semibold text-danger">
            {job.rejectedRows.toLocaleString()}
          </p>
          <p className="text-xs text-text-muted">Rejected</p>
        </div>
        <div className="text-center">
          <p className="text-lg font-semibold text-text-muted">
            {job.duplicateRows.toLocaleString()}
          </p>
          <p className="text-xs text-text-muted">Duplicates</p>
        </div>
        <div className="text-center">
          <p className="text-lg font-semibold">
            {job.totalRows.toLocaleString()}
          </p>
          <p className="text-xs text-text-muted">Total</p>
        </div>
      </div>

      {job.rejectedRows > 0 ? (
        <div className="grid gap-3">
          <div className="flex items-center justify-between gap-3">
            <p className="text-sm font-medium">
              Rejected rows ({job.rejectedRows.toLocaleString()})
            </p>
            {errors.length > 0 ? (
              <Button
                type="button"
                variant="outline"
                size="sm"
                onClick={() => exportErrorsCSV(errors, job.fileName)}
              >
                Export CSV
              </Button>
            ) : null}
          </div>

          {loading ? (
            <p className="text-sm text-text-muted">Loading rejection details…</p>
          ) : fetchError ? (
            <p className="text-sm text-text-muted">
              Could not load rejection details. Try refreshing the page.
            </p>
          ) : (
            <DataTable
              columns={[
                { key: "row", label: "Row" },
                { key: "column", label: "Column" },
                { key: "error", label: "Error message" },
              ]}
              rows={errors.map((e) => ({
                row: (
                  <span className="mono text-sm text-text-muted">
                    #{e.rowNumber}
                  </span>
                ),
                column: (
                  <span className="mono text-sm">{e.column}</span>
                ),
                error: (
                  <span className="text-sm text-text-muted">{e.errorMessage}</span>
                ),
              }))}
            />
          )}
        </div>
      ) : (
        <div className="surface-panel-muted rounded-lg p-4 text-center">
          <p className="font-medium">All rows accepted</p>
          <p className="mt-1 text-sm text-text-muted">
            No rejections — every contact passed validation.
          </p>
        </div>
      )}

      <div className="flex justify-end gap-3">
        <Button asChild variant="outline">
          <Link href="/contacts/import">Run another import</Link>
        </Button>
        <Button asChild>
          <Link href="/contacts">View contacts</Link>
        </Button>
      </div>
    </div>
  );
}
