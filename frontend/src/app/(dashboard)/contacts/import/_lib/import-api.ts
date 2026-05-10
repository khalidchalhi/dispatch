import type { ImportJob, ImportJobStatus } from "@/types/import";

type ApiImportJobStatus =
  | "queued"
  | "parsing"
  | "validating"
  | "upserting"
  | "complete"
  | "failed"
  | "cancelled";

export type ApiImportJobResponse = {
  id: string;
  status: ApiImportJobStatus;
  file_name: string;
  total_rows: number | null;
  accepted_rows: number;
  rejected_rows: number;
  duplicate_rows: number;
  created_at: string;
  completed_at: string | null;
};

export type ApiImportErrorRowResponse = {
  row_number: number;
  parsed_email: string | null;
  error_reason: string | null;
  raw_data: Record<string, unknown>;
};

function toImportJobStatus(status: ApiImportJobStatus): ImportJobStatus {
  if (status === "complete") return "completed";
  if (status === "failed" || status === "cancelled") return "failed";
  if (status === "queued") return "pending";
  return "processing";
}

export function toImportJob(api: ApiImportJobResponse): ImportJob {
  const processedRows = api.accepted_rows + api.rejected_rows;
  const totalRows =
    typeof api.total_rows === "number" ? api.total_rows : Math.max(processedRows, 0);
  return {
    id: api.id,
    status: toImportJobStatus(api.status),
    fileName: api.file_name,
    totalRows,
    processedRows,
    acceptedRows: api.accepted_rows,
    rejectedRows: api.rejected_rows,
    duplicateRows: api.duplicate_rows,
    createdAt: api.created_at,
    completedAt: api.completed_at,
  };
}
