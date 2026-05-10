"use client";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import type { CampaignMessage, MessageStatus } from "@/types/campaign";

const messageStatusVariant: Record<
  MessageStatus,
  "muted" | "warning" | "success" | "outline" | "danger"
> = {
  queued: "muted",
  sending: "warning",
  sent: "outline",
  delivered: "success",
  opened: "success",
  clicked: "success",
  bounced: "danger",
  complained: "danger",
  failed: "danger",
};

const STATUS_OPTIONS: { value: MessageStatus | ""; label: string }[] = [
  { value: "", label: "All statuses" },
  { value: "queued", label: "Queued" },
  { value: "sending", label: "Sending" },
  { value: "sent", label: "Sent" },
  { value: "delivered", label: "Delivered" },
  { value: "bounced", label: "Bounced" },
  { value: "complained", label: "Complained" },
  { value: "failed", label: "Failed" },
];

type MessagesTableProps = {
  messages: CampaignMessage[];
  nextCursor: string | null;
  statusFilter: string;
  onStatusFilterChange: (v: string) => void;
  onLoadMore: () => void;
  isLoadingMore: boolean;
  selectedMessageId: string | null;
  onSelectMessage: (id: string) => void;
};

export function MessagesTable({
  messages,
  nextCursor,
  statusFilter,
  onStatusFilterChange,
  onLoadMore,
  isLoadingMore,
  selectedMessageId,
  onSelectMessage,
}: MessagesTableProps) {
  function formatTime(iso: string) {
    try {
      return new Date(iso).toLocaleTimeString([], {
        hour: "2-digit",
        minute: "2-digit",
        second: "2-digit",
      });
    } catch {
      return iso;
    }
  }

  return (
    <section className="surface-panel p-5 grid gap-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h3 className="section-title">Messages</h3>
        <div className="flex flex-wrap items-center gap-2">
          <select
            className="field h-9"
            value={statusFilter}
            onChange={(e) => onStatusFilterChange(e.target.value)}
            aria-label="Filter by status"
          >
            {STATUS_OPTIONS.map((o) => (
              <option key={o.value} value={o.value}>
                {o.label}
              </option>
            ))}
          </select>
        </div>
      </div>

      {messages.length === 0 ? (
        <p className="text-sm text-text-muted py-4 text-center">
          No messages match the current filter.
        </p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-border text-left">
                <th className="pb-2 pr-4 font-medium text-text-muted">Email</th>
                <th className="pb-2 pr-4 font-medium text-text-muted">Status</th>
                <th className="pb-2 pr-4 font-medium text-text-muted">Flags</th>
                <th className="pb-2 font-medium text-text-muted text-right">
                  Last event
                </th>
              </tr>
            </thead>
            <tbody>
              {messages.map((msg) => (
                <tr
                  key={msg.id}
                  className={`border-b border-border/50 cursor-pointer transition-colors hover:bg-surface-muted ${
                    selectedMessageId === msg.id ? "bg-primary/5" : ""
                  }`}
                  onClick={() => onSelectMessage(msg.id)}
                  role="button"
                  tabIndex={0}
                  onKeyDown={(e) => {
                    if (e.key === "Enter" || e.key === " ")
                      onSelectMessage(msg.id);
                  }}
                  aria-pressed={selectedMessageId === msg.id}
                >
                  <td className="py-2.5 pr-4 mono text-xs">{msg.email}</td>
                  <td className="py-2.5 pr-4">
                    <Badge variant={messageStatusVariant[msg.status]}>
                      {msg.status}
                    </Badge>
                  </td>
                  <td className="py-2.5 pr-4">
                    <span className="flex gap-1">
                      {msg.hasBounce && (
                        <Badge variant="danger">bounce</Badge>
                      )}
                      {msg.hasComplaint && (
                        <Badge variant="danger">complaint</Badge>
                      )}
                      {msg.hasClick && (
                        <Badge variant="success">click</Badge>
                      )}
                    </span>
                  </td>
                  <td className="py-2.5 text-right mono text-xs text-text-muted">
                    {formatTime(msg.lastEventAt)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {nextCursor && (
        <div className="flex justify-center pt-2">
          <Button
            type="button"
            variant="outline"
            disabled={isLoadingMore}
            onClick={onLoadMore}
          >
            {isLoadingMore ? "Loading…" : "Load more"}
          </Button>
        </div>
      )}
    </section>
  );
}
