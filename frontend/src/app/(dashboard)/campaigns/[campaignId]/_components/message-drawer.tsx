"use client";

import * as DialogPrimitive from "@radix-ui/react-dialog";
import { X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import type { CampaignMessageDetail, MessageEventType } from "@/types/campaign";

const EVENT_LABELS: Record<MessageEventType, string> = {
  queued: "Queued",
  sent: "Sent to SES",
  delivered: "Delivered",
  opened: "Opened",
  clicked: "Clicked",
  bounced: "Bounced",
  complained: "Complaint",
  failed: "Failed",
};

const EVENT_COLOR: Record<MessageEventType, string> = {
  queued: "bg-muted",
  sent: "bg-[var(--chart-1)]",
  delivered: "bg-[var(--chart-3)]",
  opened: "bg-[var(--chart-3)]",
  clicked: "bg-[var(--chart-3)]",
  bounced: "bg-danger",
  complained: "bg-danger",
  failed: "bg-danger",
};

type MessageDrawerProps = {
  detail: CampaignMessageDetail | null;
  open: boolean;
  onClose: () => void;
  onRequeue: () => void;
  isRequeuing: boolean;
  isLoading: boolean;
};

export function MessageDrawer({
  detail,
  open,
  onClose,
  onRequeue,
  isRequeuing,
  isLoading,
}: MessageDrawerProps) {
  const canRequeue = detail?.status === "failed";

  return (
    <DialogPrimitive.Root open={open} onOpenChange={(v) => { if (!v) onClose(); }}>
      <DialogPrimitive.Portal>
        <DialogPrimitive.Overlay className="fixed inset-0 z-40 bg-black/20" />
        <DialogPrimitive.Content
          aria-describedby={undefined}
          className="fixed right-0 top-0 z-50 h-full w-full max-w-2xl overflow-y-auto border-l border-border bg-surface shadow-xl focus:outline-none"
        >
          <div className="flex items-center justify-between gap-3 border-b border-border px-6 py-4">
            <DialogPrimitive.Title className="text-base font-semibold">
              Message inspector
            </DialogPrimitive.Title>
            <div className="flex items-center gap-2">
              {canRequeue ? (
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  disabled={isRequeuing}
                  onClick={() => void onRequeue()}
                >
                  {isRequeuing ? "Requeueing…" : "Re-queue message"}
                </Button>
              ) : null}
              <DialogPrimitive.Close
                className="rounded-[8px] p-1 text-text-muted transition-colors hover:bg-surface-muted hover:text-foreground"
                onClick={onClose}
              >
                <X className="h-4 w-4" />
                <span className="sr-only">Close</span>
              </DialogPrimitive.Close>
            </div>
          </div>

          {detail && !isLoading ? (
            <div className="p-6">
              <Tabs defaultValue="overview">
                <TabsList>
                  <TabsTrigger value="overview">Overview</TabsTrigger>
                  <TabsTrigger value="email">Rendered email</TabsTrigger>
                  <TabsTrigger value="timeline">Event timeline</TabsTrigger>
                </TabsList>

                <TabsContent value="overview">
                  <dl className="summary-list mt-4">
                    <div className="summary-row">
                      <dt className="text-sm font-medium">Message ID</dt>
                      <dd className="mono text-xs text-text-muted">{detail.id}</dd>
                    </div>
                    <div className="summary-row">
                      <dt className="text-sm font-medium">Contact</dt>
                      <dd className="mono text-xs text-text-muted">{detail.email}</dd>
                    </div>
                    <div className="summary-row">
                      <dt className="text-sm font-medium">Contact ID</dt>
                      <dd className="mono text-xs text-text-muted">{detail.contactId}</dd>
                    </div>
                    <div className="summary-row">
                      <dt className="text-sm font-medium">Sender profile</dt>
                      <dd className="text-sm">{detail.senderProfileName}</dd>
                    </div>
                    {detail.sesMessageId && (
                      <div className="summary-row">
                        <dt className="text-sm font-medium">SES message ID</dt>
                        <dd className="mono text-xs text-text-muted">
                          {detail.sesMessageId}
                        </dd>
                      </div>
                    )}
                    <div className="summary-row">
                      <dt className="text-sm font-medium">Status</dt>
                      <dd className="text-sm">{detail.status}</dd>
                    </div>
                  </dl>
                </TabsContent>

                <TabsContent value="email">
                  {detail.renderedHtml ? (
                    <iframe
                      title="Rendered email preview"
                      srcDoc={detail.renderedHtml}
                      sandbox="allow-same-origin"
                      className="mt-4 h-[60vh] w-full rounded-lg border border-border bg-white"
                    />
                  ) : (
                    <p className="mt-4 text-sm text-text-muted">
                      No rendered HTML available for this message.
                    </p>
                  )}
                </TabsContent>

                <TabsContent value="timeline">
                  <ol className="mt-4 grid gap-3" aria-label="Event timeline">
                    {detail.events.map((event) => (
                      <li key={event.id} className="flex gap-3">
                        <div className="flex flex-col items-center gap-1">
                          <span
                            className={`mt-1 h-2.5 w-2.5 shrink-0 rounded-full ${EVENT_COLOR[event.type]}`}
                          />
                        </div>
                        <div className="flex-1 min-w-0">
                          <p className="text-sm font-medium">
                            {EVENT_LABELS[event.type]}
                          </p>
                          {event.detail && (
                            <p className="text-xs text-text-muted mt-0.5">
                              {event.detail}
                            </p>
                          )}
                          <p className="mono text-xs text-text-muted mt-0.5">
                            {new Date(event.timestamp).toLocaleString()}
                          </p>
                        </div>
                      </li>
                    ))}
                  </ol>
                </TabsContent>
              </Tabs>
            </div>
          ) : (
            <div className="p-6">
              <p className="text-sm text-text-muted">
                {isLoading ? "Loading message…" : "Message details unavailable."}
              </p>
            </div>
          )}
        </DialogPrimitive.Content>
      </DialogPrimitive.Portal>
    </DialogPrimitive.Root>
  );
}
