"use client";

import { useState, useEffect, useRef, useCallback } from "react";
import { toast } from "sonner";
import { CampaignHeader } from "./campaign-header";
import { CampaignMetrics } from "./campaign-metrics";
import { MessagesTable } from "./messages-table";
import { MessageDrawer } from "./message-drawer";
import { clientJson } from "@/lib/api/client";
import { apiEndpoints } from "@/lib/api/endpoints";
import {
  mergeCampaignDetailFromApi,
  type CampaignByIdApiResponse,
} from "@/app/(dashboard)/campaigns/_lib/campaigns-api";
import type {
  CampaignDetail,
  CampaignMessage,
  CampaignMessageDetail,
  CampaignStatus,
  MessageStatus,
  MessagesPage,
} from "@/types/campaign";
import type { BreakerEntryState } from "@/types/ops";

const POLL_INTERVAL_MS = 15_000;
const MESSAGES_PAGE_SIZE = 50;
const MAX_DRAWER_PAGES = 20;

type CampaignMessagesApiResponse = {
  items: Array<{
    message_id: string;
    campaign_id: string | null;
    to_email: string;
    status: string;
    has_bounce: boolean;
    has_click: boolean;
    has_complaint: boolean;
    ses_message_id: string | null;
    last_event_at: string;
  }>;
  next_cursor: string | null;
};

type CampaignMonitorProps = {
  initialDetail: CampaignDetail;
  initialPage: MessagesPage;
  domainBreakerState?: BreakerEntryState;
  domainId?: string;
};

function toMessageStatus(value: string): MessageStatus {
  if (value === "queued") return "queued";
  if (value === "sending") return "sending";
  if (value === "sent") return "sent";
  if (value === "delivered") return "delivered";
  if (value === "opened") return "opened";
  if (value === "clicked") return "clicked";
  if (value === "bounced") return "bounced";
  if (value === "complained") return "complained";
  return "failed";
}

function toCampaignMessage(
  campaignId: string,
  item: CampaignMessagesApiResponse["items"][number],
): CampaignMessage {
  return {
    id: item.message_id,
    campaignId: item.campaign_id ?? campaignId,
    email: item.to_email,
    status: toMessageStatus(item.status),
    lastEventAt: item.last_event_at,
    hasBounce: item.has_bounce,
    hasClick: item.has_click,
    hasComplaint: item.has_complaint,
    sesMessageId: item.ses_message_id,
  };
}

function toDrawerDetail(message: CampaignMessage): CampaignMessageDetail {
  return {
    ...message,
    contactId: "Unavailable",
    senderProfileName: "Unavailable",
    events: [],
    renderedHtml: null,
  };
}

export function CampaignMonitor({
  initialDetail,
  initialPage,
  domainBreakerState = "closed",
  domainId,
}: CampaignMonitorProps) {
  const [detail, setDetail] = useState<CampaignDetail>(initialDetail);
  const [messages, setMessages] = useState<CampaignMessage[]>(initialPage.messages);
  const [nextCursor, setNextCursor] = useState<string | null>(initialPage.nextCursor);
  const [statusFilter, setStatusFilter] = useState("");
  const [isLoadingMore, setIsLoadingMore] = useState(false);
  const [selectedMessageId, setSelectedMessageId] = useState<string | null>(null);
  const [messageDetail, setMessageDetail] = useState<CampaignMessageDetail | null>(null);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [isDrawerLoading, setIsDrawerLoading] = useState(false);
  const [isRequeuingMessage, setIsRequeuingMessage] = useState(false);

  const pollTimerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const isHiddenRef = useRef(false);
  const isPollingRef = useRef(false);

  const stopPolling = useCallback(() => {
    if (pollTimerRef.current) {
      clearInterval(pollTimerRef.current);
      pollTimerRef.current = null;
    }
  }, []);

  const pollDetail = useCallback(async () => {
    if (isHiddenRef.current || isPollingRef.current) return;

    isPollingRef.current = true;
    try {
      const fresh = await clientJson<CampaignByIdApiResponse>(
        apiEndpoints.campaigns.byId(detail.id),
      );
      setDetail((prev) => mergeCampaignDetailFromApi(prev, fresh));
    } catch {
      // polling noise intentionally suppressed
    } finally {
      isPollingRef.current = false;
    }
  }, [detail.id]);

  const startPolling = useCallback(() => {
    stopPolling();
    pollTimerRef.current = setInterval(() => {
      void pollDetail();
    }, POLL_INTERVAL_MS);
  }, [pollDetail, stopPolling]);

  useEffect(() => {
    if (detail.status === "running") {
      startPolling();
    } else {
      stopPolling();
    }
    return stopPolling;
  }, [detail.status, startPolling, stopPolling]);

  useEffect(() => {
    function handleVisibilityChange() {
      isHiddenRef.current = document.visibilityState === "hidden";
      if (isHiddenRef.current) {
        stopPolling();
      } else if (detail.status === "running") {
        startPolling();
      }
    }
    document.addEventListener("visibilitychange", handleVisibilityChange);
    return () => {
      document.removeEventListener("visibilitychange", handleVisibilityChange);
    };
  }, [detail.status, startPolling, stopPolling]);

  const fetchMessagesPage = useCallback(
    async (cursor: string | null, filter: string) => {
      const response = await clientJson<CampaignMessagesApiResponse>(
        apiEndpoints.campaigns.messages(detail.id),
        {
          query: {
            limit: MESSAGES_PAGE_SIZE,
            cursor: cursor ?? undefined,
            status: filter || undefined,
          },
        },
      );
      return {
        messages: response.items.map((item) => toCampaignMessage(detail.id, item)),
        nextCursor: response.next_cursor,
      };
    },
    [detail.id],
  );

  const refreshMessages = useCallback(
    async (filter: string) => {
      const page = await fetchMessagesPage(null, filter);
      setMessages(page.messages);
      setNextCursor(page.nextCursor);
      return page;
    },
    [fetchMessagesPage],
  );

  function handleStatusChange(newStatus: CampaignStatus) {
    setDetail((prev) => ({ ...prev, status: newStatus }));
  }

  function handleStatusFilterChange(value: string) {
    setStatusFilter(value);
    void refreshMessages(value).catch(() => {
      toast.error("Failed to refresh messages.");
    });
  }

  async function handleLoadMore() {
    if (!nextCursor || isLoadingMore) return;
    setIsLoadingMore(true);
    try {
      const page = await fetchMessagesPage(nextCursor, statusFilter);
      setMessages((prev) => [...prev, ...page.messages]);
      setNextCursor(page.nextCursor);
    } catch {
      toast.error("Failed to load more messages.");
    } finally {
      setIsLoadingMore(false);
    }
  }

  async function hydrateDrawerMessage(messageId: string) {
    setIsDrawerLoading(true);
    try {
      let cursor: string | null = null;
      for (let pageIndex = 0; pageIndex < MAX_DRAWER_PAGES; pageIndex += 1) {
        const page = await fetchMessagesPage(cursor, statusFilter);
        const found = page.messages.find((message) => message.id === messageId);
        if (found) {
          setMessageDetail(toDrawerDetail(found));
          return;
        }
        if (!page.nextCursor) break;
        cursor = page.nextCursor;
      }

      setMessageDetail(null);
      toast.error("Message could not be loaded.");
    } catch {
      setMessageDetail(null);
      toast.error("Failed to load message details.");
    } finally {
      setIsDrawerLoading(false);
    }
  }

  function handleSelectMessage(id: string) {
    setSelectedMessageId(id);
    setDrawerOpen(true);
    void hydrateDrawerMessage(id);
  }

  function handleCloseDrawer() {
    setDrawerOpen(false);
    setSelectedMessageId(null);
  }

  async function handleRequeueSelectedMessage() {
    if (!messageDetail || isRequeuingMessage) return;
    setIsRequeuingMessage(true);
    try {
      await clientJson(
        apiEndpoints.campaigns.messageRequeue(detail.id, messageDetail.id),
        { method: "POST" },
      );
      toast.success("Message re-queued.");
      await refreshMessages(statusFilter);
      setMessageDetail((prev) =>
        prev ? { ...prev, status: "queued", hasBounce: false, hasComplaint: false } : prev,
      );
    } catch {
      toast.error("Re-queue failed. Please retry.");
    } finally {
      setIsRequeuingMessage(false);
    }
  }

  return (
    <div className="grid gap-6">
      <CampaignHeader
        detail={detail}
        onStatusChange={handleStatusChange}
        domainBreakerState={domainBreakerState}
        domainId={domainId}
      />
      <CampaignMetrics kpis={detail.kpis} velocityPoints={detail.velocityPoints} />
      <MessagesTable
        messages={messages}
        nextCursor={nextCursor}
        statusFilter={statusFilter}
        onStatusFilterChange={handleStatusFilterChange}
        onLoadMore={handleLoadMore}
        isLoadingMore={isLoadingMore}
        selectedMessageId={selectedMessageId}
        onSelectMessage={handleSelectMessage}
      />
      <MessageDrawer
        detail={messageDetail}
        open={drawerOpen}
        onClose={handleCloseDrawer}
        onRequeue={handleRequeueSelectedMessage}
        isRequeuing={isRequeuingMessage}
        isLoading={isDrawerLoading}
      />
    </div>
  );
}
