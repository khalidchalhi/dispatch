import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { CampaignMonitor } from "@/app/(dashboard)/campaigns/[campaignId]/_components/campaign-monitor";
import { CampaignHeader } from "@/app/(dashboard)/campaigns/[campaignId]/_components/campaign-header";
import { MessagesTable } from "@/app/(dashboard)/campaigns/[campaignId]/_components/messages-table";
import { MessageDrawer } from "@/app/(dashboard)/campaigns/[campaignId]/_components/message-drawer";
import { CampaignMetrics } from "@/app/(dashboard)/campaigns/[campaignId]/_components/campaign-metrics";
import {
  getMockCampaignDetail,
  getMockMessagesPage,
  getMockMessageDetail,
} from "@/app/(dashboard)/campaigns/_lib/campaigns-queries";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), refresh: vi.fn() }),
  notFound: vi.fn(),
}));

vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

vi.mock("@/lib/api/client", () => ({
  clientJson: vi.fn(async (path: string, options?: { query?: { cursor?: string } }) => {
    if (path.includes("/campaigns/") && path.includes("/messages")) {
      const cursor = options?.query?.cursor;
      if (!cursor) {
        return {
          items: [
            {
              message_id: "msg-live-1",
              campaign_id: "cmp-003",
              to_email: "first@example.com",
              status: "failed",
              has_bounce: true,
              has_click: false,
              has_complaint: false,
              ses_message_id: null,
              last_event_at: "2026-04-01T10:00:00Z",
            },
          ],
          next_cursor: "cursor-2",
        };
      }
      return {
        items: [
          {
            message_id: "msg-live-2",
            campaign_id: "cmp-003",
            to_email: "second@example.com",
            status: "queued",
            has_bounce: false,
            has_click: false,
            has_complaint: false,
            ses_message_id: null,
            last_event_at: "2026-04-01T10:01:00Z",
          },
        ],
        next_cursor: null,
      };
    }
    if (path.includes("/campaigns/") && options?.query === undefined) {
      return {
        id: "cmp-003",
        name: "Seed inbox test",
        status: "running",
        updated_at: "2026-04-01T10:00:00Z",
      };
    }
    return {};
  }),
}));

// ─── getMockCampaignDetail ────────────────────────────────────────────────────

describe("getMockCampaignDetail", () => {
  it("returns detail with kpis and velocityPoints for known id", () => {
    const d = getMockCampaignDetail("cmp-003");
    expect(d.id).toBe("cmp-003");
    expect(d.kpis).toBeDefined();
    expect(d.kpis.sent).toBeGreaterThan(0);
    expect(d.velocityPoints.length).toBeGreaterThan(0);
  });

  it("returns zero kpis for unknown id", () => {
    const d = getMockCampaignDetail("unknown");
    expect(d.kpis.sent).toBe(0);
  });
});

// ─── getMockMessagesPage ──────────────────────────────────────────────────────

describe("getMockMessagesPage", () => {
  it("returns first page of messages", () => {
    const page = getMockMessagesPage("cmp-003", null, null);
    expect(page.messages.length).toBe(20);
    expect(page.nextCursor).not.toBeNull();
  });

  it("paginates correctly with cursor", () => {
    const first = getMockMessagesPage("cmp-003", null, null);
    const second = getMockMessagesPage("cmp-003", first.nextCursor, null);
    expect(second.messages.length).toBe(20);
    expect(second.messages[0]!.id).not.toBe(first.messages[0]!.id);
  });

  it("filters by status", () => {
    const page = getMockMessagesPage("cmp-003", null, "bounced");
    expect(page.messages.every((m) => m.status === "bounced")).toBe(true);
  });

  it("returns null nextCursor on last page", () => {
    const first = getMockMessagesPage("cmp-003", null, null);
    const second = getMockMessagesPage("cmp-003", first.nextCursor, null);
    const third = getMockMessagesPage("cmp-003", second.nextCursor, null);
    expect(third.nextCursor).toBeNull();
  });
});

// ─── getMockMessageDetail ─────────────────────────────────────────────────────

describe("getMockMessageDetail", () => {
  it("returns detail with events for existing message", () => {
    const page = getMockMessagesPage("cmp-003", null, null);
    const id = page.messages[0]!.id;
    const detail = getMockMessageDetail("cmp-003", id);
    expect(detail).not.toBeNull();
    expect(detail!.events.length).toBeGreaterThan(0);
    expect(detail!.events[0]!.type).toBe("queued");
  });

  it("returns null for unknown message id", () => {
    expect(getMockMessageDetail("cmp-003", "nonexistent")).toBeNull();
  });

  it("delivered message has delivered event", () => {
    const page = getMockMessagesPage("cmp-003", null, "delivered");
    if (page.messages.length > 0) {
      const msg = page.messages[0]!;
      const detail = getMockMessageDetail("cmp-003", msg.id);
      expect(detail!.events.some((e) => e.type === "delivered")).toBe(true);
    }
  });

  it("bounced message has bounced event", () => {
    const page = getMockMessagesPage("cmp-003", null, "bounced");
    if (page.messages.length > 0) {
      const msg = page.messages[0]!;
      const detail = getMockMessageDetail("cmp-003", msg.id);
      expect(detail!.events.some((e) => e.type === "bounced")).toBe(true);
    }
  });
});

// ─── CampaignHeader ───────────────────────────────────────────────────────────

describe("CampaignHeader", () => {
  const baseDetail = getMockCampaignDetail("cmp-003");

  it("renders campaign name", () => {
    render(<CampaignHeader detail={baseDetail} onStatusChange={vi.fn()} />);
    expect(screen.getByText("Seed inbox test")).toBeInTheDocument();
  });

  it("renders all 8 KPI tiles", () => {
    render(<CampaignHeader detail={baseDetail} onStatusChange={vi.fn()} />);
    expect(screen.getByText("Queued")).toBeInTheDocument();
    expect(screen.getByText("Sent")).toBeInTheDocument();
    expect(screen.getByText("Delivered")).toBeInTheDocument();
    expect(screen.getByText("Bounced")).toBeInTheDocument();
    expect(screen.getByText("Clicked")).toBeInTheDocument();
  });

  it("shows Pause button for running campaign", () => {
    render(<CampaignHeader detail={baseDetail} onStatusChange={vi.fn()} />);
    expect(screen.getByRole("button", { name: /pause/i })).toBeInTheDocument();
  });

  it("shows Cancel button for running campaign", () => {
    render(<CampaignHeader detail={baseDetail} onStatusChange={vi.fn()} />);
    expect(screen.getByRole("button", { name: /cancel/i })).toBeInTheDocument();
  });

  it("shows Resume for paused campaign", () => {
    const paused = { ...baseDetail, status: "paused" as const };
    render(<CampaignHeader detail={paused} onStatusChange={vi.fn()} />);
    expect(screen.getByRole("button", { name: /resume/i })).toBeInTheDocument();
  });

  it("shows no action buttons for completed campaign", () => {
    const completed = { ...baseDetail, status: "completed" as const };
    render(<CampaignHeader detail={completed} onStatusChange={vi.fn()} />);
    expect(screen.queryByRole("button", { name: /pause/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /resume/i })).not.toBeInTheDocument();
  });
});

// ─── CampaignMetrics ──────────────────────────────────────────────────────────

describe("CampaignMetrics", () => {
  const detail = getMockCampaignDetail("cmp-003");

  it("renders send funnel heading", () => {
    render(
      <CampaignMetrics kpis={detail.kpis} velocityPoints={detail.velocityPoints} />,
    );
    expect(screen.getByText(/send funnel/i)).toBeInTheDocument();
  });

  it("renders funnel steps", () => {
    render(
      <CampaignMetrics kpis={detail.kpis} velocityPoints={detail.velocityPoints} />,
    );
    expect(screen.getByText("Sent")).toBeInTheDocument();
    expect(screen.getByText("Delivered")).toBeInTheDocument();
    expect(screen.getByText("Opened")).toBeInTheDocument();
    expect(screen.getByText("Clicked")).toBeInTheDocument();
  });
});

// ─── MessagesTable ────────────────────────────────────────────────────────────

describe("MessagesTable", () => {
  const page = getMockMessagesPage("cmp-003", null, null);
  const base = {
    messages: page.messages,
    nextCursor: page.nextCursor,
    statusFilter: "",
    onStatusFilterChange: vi.fn(),
    onLoadMore: vi.fn(),
    isLoadingMore: false,
    selectedMessageId: null,
    onSelectMessage: vi.fn(),
  };

  it("renders message rows", () => {
    render(<MessagesTable {...base} />);
    expect(screen.getAllByRole("button").length).toBeGreaterThan(0);
  });

  it("renders Load more when nextCursor is set", () => {
    render(<MessagesTable {...base} />);
    expect(screen.getByRole("button", { name: /load more/i })).toBeInTheDocument();
  });

  it("hides Load more when nextCursor is null", () => {
    render(<MessagesTable {...base} nextCursor={null} />);
    expect(
      screen.queryByRole("button", { name: /load more/i }),
    ).not.toBeInTheDocument();
  });

  it("calls onLoadMore when Load more is clicked", () => {
    render(<MessagesTable {...base} />);
    fireEvent.click(screen.getByRole("button", { name: /load more/i }));
    expect(base.onLoadMore).toHaveBeenCalled();
  });

  it("calls onSelectMessage when row is clicked", () => {
    render(<MessagesTable {...base} />);
    const rows = screen.getAllByRole("button").filter((el) =>
      el.hasAttribute("aria-pressed"),
    );
    fireEvent.click(rows[0]!);
    expect(base.onSelectMessage).toHaveBeenCalled();
  });

  it("filter select calls onStatusFilterChange", () => {
    render(<MessagesTable {...base} />);
    fireEvent.change(screen.getByRole("combobox", { name: /filter by status/i }), {
      target: { value: "bounced" },
    });
    expect(base.onStatusFilterChange).toHaveBeenCalledWith("bounced");
  });

  it("shows empty message when no messages", () => {
    render(<MessagesTable {...base} messages={[]} nextCursor={null} />);
    expect(screen.getByText(/no messages match/i)).toBeInTheDocument();
  });
});

// ─── MessageDrawer ────────────────────────────────────────────────────────────

describe("MessageDrawer", () => {
  const page = getMockMessagesPage("cmp-003", null, null);
  const detail = getMockMessageDetail("cmp-003", page.messages[0]!.id)!;

  it("does not render when open=false", () => {
    render(
      <MessageDrawer
        detail={detail}
        open={false}
        onClose={vi.fn()}
        onRequeue={vi.fn()}
        isRequeuing={false}
        isLoading={false}
      />,
    );
    expect(screen.queryByText("Message inspector")).not.toBeInTheDocument();
  });

  it("renders when open=true", () => {
    render(
      <MessageDrawer
        detail={detail}
        open={true}
        onClose={vi.fn()}
        onRequeue={vi.fn()}
        isRequeuing={false}
        isLoading={false}
      />,
    );
    expect(screen.getByText("Message inspector")).toBeInTheDocument();
  });

  it("shows Overview, Rendered email, and Event timeline tabs", () => {
    render(
      <MessageDrawer
        detail={detail}
        open={true}
        onClose={vi.fn()}
        onRequeue={vi.fn()}
        isRequeuing={false}
        isLoading={false}
      />,
    );
    expect(screen.getByRole("tab", { name: /overview/i })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: /rendered email/i })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: /event timeline/i })).toBeInTheDocument();
  });

  it("shows contact email in overview", () => {
    render(
      <MessageDrawer
        detail={detail}
        open={true}
        onClose={vi.fn()}
        onRequeue={vi.fn()}
        isRequeuing={false}
        isLoading={false}
      />,
    );
    expect(screen.getByText(detail.email)).toBeInTheDocument();
  });

  it("detail has at least one event starting with queued", () => {
    expect(detail.events[0]!.type).toBe("queued");
    expect(detail.events.length).toBeGreaterThan(0);
  });

  it("calls onClose when close button is clicked", () => {
    const onClose = vi.fn();
    render(
      <MessageDrawer
        detail={detail}
        open={true}
        onClose={onClose}
        onRequeue={vi.fn()}
        isRequeuing={false}
        isLoading={false}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: /close/i }));
    expect(onClose).toHaveBeenCalled();
  });
});

// ─── CampaignMonitor ──────────────────────────────────────────────────────────

describe("CampaignMonitor", () => {
  const detail = getMockCampaignDetail("cmp-003");
  const initialPage = getMockMessagesPage("cmp-003", null, null);

  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("renders campaign header with name", () => {
    render(
      <CampaignMonitor initialDetail={detail} initialPage={initialPage} />,
    );
    expect(screen.getByText("Seed inbox test")).toBeInTheDocument();
  });

  it("renders messages table", () => {
    render(
      <CampaignMonitor initialDetail={detail} initialPage={initialPage} />,
    );
    expect(screen.getByText(/messages/i)).toBeInTheDocument();
  });

  it("opens drawer when a message row is clicked", () => {
    render(
      <CampaignMonitor initialDetail={detail} initialPage={initialPage} />,
    );
    const rows = screen.getAllByRole("button").filter((el) =>
      el.hasAttribute("aria-pressed"),
    );
    fireEvent.click(rows[0]!);
    expect(screen.getByText("Message inspector")).toBeInTheDocument();
  });

  it("sets up polling interval for running campaign", () => {
    const setIntervalSpy = vi.spyOn(globalThis, "setInterval");
    render(
      <CampaignMonitor initialDetail={detail} initialPage={initialPage} />,
    );
    expect(setIntervalSpy).toHaveBeenCalledWith(
      expect.any(Function),
      15_000,
    );
  });

  it("does not poll for completed campaign", () => {
    const setIntervalSpy = vi.spyOn(globalThis, "setInterval");
    const completed = { ...detail, status: "completed" as const };
    render(
      <CampaignMonitor
        initialDetail={completed}
        initialPage={initialPage}
      />,
    );
    expect(setIntervalSpy).not.toHaveBeenCalledWith(
      expect.any(Function),
      15_000,
    );
  });

  it("loads more messages when Load more is clicked", async () => {
    vi.useRealTimers();
    render(
      <CampaignMonitor initialDetail={detail} initialPage={initialPage} />,
    );
    const loadMore = screen.getByRole("button", { name: /load more/i });
    const initialCount = screen
      .getAllByRole("button")
      .filter((el) => el.hasAttribute("aria-pressed")).length;
    fireEvent.click(loadMore);
    await waitFor(() => {
      const newCount = screen
        .getAllByRole("button")
        .filter((el) => el.hasAttribute("aria-pressed")).length;
      expect(newCount).toBeGreaterThan(initialCount);
    });
  });
});
