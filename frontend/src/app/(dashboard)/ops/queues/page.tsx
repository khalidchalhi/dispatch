import { SectionPanel } from "@/components/patterns/section-panel";
import { serverJson } from "@/lib/api/server";
import { apiEndpoints as ENDPOINTS } from "@/lib/api/endpoints";
import type { QueueRow } from "@/types/ops";
import { QueuesViewer } from "./_components/queues-viewer";

type QueueApiItem = {
  domain_id?: string;
  domainId?: string;
  domain_name?: string;
  domainName?: string;
  queue_name?: string;
  queueName?: string;
  worker_count?: number;
  workerCount?: number;
  queue_depth?: number;
  queueDepth?: number;
  oldest_queued_age_seconds?: number | null;
  oldestQueuedAgeSeconds?: number | null;
  denials_per_minute?: number;
  denialsPerMinute?: number;
  updated_at?: string;
  updatedAt?: string;
};

type QueueApiResponse = {
  items?: QueueApiItem[];
};

function toQueueRow(item: QueueApiItem, index: number): QueueRow {
  return {
    domainId: item.domain_id ?? item.domainId ?? `domain-${index}`,
    domainName: item.domain_name ?? item.domainName ?? "Unknown domain",
    queueName: item.queue_name ?? item.queueName ?? `send.unknown-${index}`,
    workerCount: item.worker_count ?? item.workerCount ?? 0,
    queueDepth: item.queue_depth ?? item.queueDepth ?? 0,
    oldestQueuedAgeSeconds:
      item.oldest_queued_age_seconds ?? item.oldestQueuedAgeSeconds ?? null,
    denialsPerMinute: item.denials_per_minute ?? item.denialsPerMinute ?? 0,
    updatedAt: item.updated_at ?? item.updatedAt ?? new Date().toISOString(),
  };
}

export default async function QueuesPage() {
  let rows: QueueRow[] = [];

  try {
    const response = await serverJson<QueueApiResponse>(ENDPOINTS.ops.queues);
    rows = (response.items ?? []).map(toQueueRow);
  } catch {
    rows = [];
  }

  return (
    <div className="page-stack">
      <header className="page-header">
        <div>
          <h1 className="page-title">Queues</h1>
          <p className="page-description">
            Per-domain send queue depth, worker counts, and denial rates.
          </p>
        </div>
      </header>

      <SectionPanel>
        <QueuesViewer initialRows={rows} />
      </SectionPanel>
    </div>
  );
}
