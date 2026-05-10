import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { CampaignWizard } from "@/app/(dashboard)/campaigns/create/_components/campaign-wizard";
import { StepDetails } from "@/app/(dashboard)/campaigns/create/_components/step-details";
import { StepSender } from "@/app/(dashboard)/campaigns/create/_components/step-sender";
import { StepTemplate } from "@/app/(dashboard)/campaigns/create/_components/step-template";
import { StepAudience } from "@/app/(dashboard)/campaigns/create/_components/step-audience";
import { StepSchedule } from "@/app/(dashboard)/campaigns/create/_components/step-schedule";
import { StepReview } from "@/app/(dashboard)/campaigns/create/_components/step-review";
import { EMPTY_DRAFT, WIZARD_STEPS, isDraftStepComplete } from "@/types/campaign";
import type { CampaignDraft } from "@/types/campaign";
import { senderProfiles } from "@/app/(dashboard)/sender-profiles/_lib/sender-profiles-queries";
import { mockTemplates, getVersionsForTemplate } from "@/app/(dashboard)/templates/_lib/templates-queries";
import { mockSegments } from "@/app/(dashboard)/segments/_lib/segments-queries";
import { lists } from "@/app/(dashboard)/lists/_lib/lists-queries";
import type { WizardTemplate } from "@/app/(dashboard)/campaigns/create/_lib/wizard-types";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), refresh: vi.fn() }),
}));

vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

vi.mock("@/lib/api/client", () => ({
  clientJson: vi.fn(async (path: string) => {
    if (path.includes("/preflight")) {
      return {
        campaign_id: "cmp-new",
        checks: [
          {
            id: "sender_profile",
            label: "Sender profile",
            severity: "ok",
            detail: "Sender profile is active",
          },
        ],
        has_critical: false,
        generated_at: "2026-01-01T00:00:00Z",
      };
    }
    if (path.includes("/launch")) {
      return {
        campaign: { id: "cmp-new" },
        campaign_run_id: "run-1",
        run_number: 1,
        snapshot_rows: 1,
        created_messages: 1,
        enqueued_messages: 1,
        already_launched: false,
      };
    }
    return { id: "cmp-new" };
  }),
}));

const localStorageMock = (() => {
  let store: Record<string, string> = {};
  return {
    getItem: (k: string) => store[k] ?? null,
    setItem: (k: string, v: string) => { store[k] = v; },
    removeItem: (k: string) => { delete store[k]; },
    clear: () => { store = {}; },
  };
})();
Object.defineProperty(window, "localStorage", { value: localStorageMock });

const filledDraft: CampaignDraft = {
  campaignId: null,
  name: "Test campaign",
  tag: "test-tag",
  senderProfileId: "sp-001",
  templateId: "tmpl-001",
  templateVersion: 2,
  audienceType: "segment",
  audienceId: "seg-001",
  scheduleType: "immediate",
  scheduledAt: "",
  timezone: "UTC",
};

const wizardTemplates: WizardTemplate[] = mockTemplates.map((template) => ({
  ...template,
  versions: getVersionsForTemplate(template.id),
}));

const wizardData = {
  senderProfiles,
  templates: wizardTemplates,
  segments: mockSegments,
  lists,
};

// ─── isDraftStepComplete ──────────────────────────────────────────────────────

describe("isDraftStepComplete", () => {
  it("step 0 requires name", () => {
    expect(isDraftStepComplete(0, { ...EMPTY_DRAFT, name: "" })).toBe(false);
    expect(isDraftStepComplete(0, { ...EMPTY_DRAFT, name: "Foo" })).toBe(true);
  });

  it("step 1 requires senderProfileId", () => {
    expect(isDraftStepComplete(1, { ...EMPTY_DRAFT, senderProfileId: "" })).toBe(false);
    expect(isDraftStepComplete(1, { ...EMPTY_DRAFT, senderProfileId: "sp-001" })).toBe(true);
  });

  it("step 2 requires templateId and templateVersion", () => {
    expect(isDraftStepComplete(2, { ...EMPTY_DRAFT, templateId: "t1", templateVersion: null })).toBe(false);
    expect(isDraftStepComplete(2, { ...EMPTY_DRAFT, templateId: "", templateVersion: 1 })).toBe(false);
    expect(isDraftStepComplete(2, { ...EMPTY_DRAFT, templateId: "t1", templateVersion: 1 })).toBe(true);
  });

  it("step 3 requires audienceId", () => {
    expect(isDraftStepComplete(3, { ...EMPTY_DRAFT, audienceId: "" })).toBe(false);
    expect(isDraftStepComplete(3, { ...EMPTY_DRAFT, audienceId: "seg-1" })).toBe(true);
  });

  it("step 4 — immediate always valid, scheduled needs scheduledAt", () => {
    expect(isDraftStepComplete(4, { ...EMPTY_DRAFT, scheduleType: "immediate" })).toBe(true);
    expect(isDraftStepComplete(4, { ...EMPTY_DRAFT, scheduleType: "scheduled", scheduledAt: "" })).toBe(false);
    expect(isDraftStepComplete(4, { ...EMPTY_DRAFT, scheduleType: "scheduled", scheduledAt: "2026-05-01T10:00" })).toBe(true);
  });

  it("unknown step returns true", () => {
    expect(isDraftStepComplete(99, EMPTY_DRAFT)).toBe(true);
  });
});

// ─── WIZARD_STEPS ─────────────────────────────────────────────────────────────

describe("WIZARD_STEPS", () => {
  it("has 6 steps in order", () => {
    expect(WIZARD_STEPS).toHaveLength(6);
    expect(WIZARD_STEPS[0]).toBe("Details");
    expect(WIZARD_STEPS[5]).toBe("Review");
  });
});

// ─── CampaignWizard ───────────────────────────────────────────────────────────

describe("CampaignWizard", () => {
  beforeEach(() => localStorageMock.clear());

  it("renders step 1 (Details) first with wizard nav", () => {
    render(<CampaignWizard {...wizardData} />);
    expect(screen.getByText("1. Details")).toBeInTheDocument();
    expect(screen.getByLabelText(/campaign name/i)).toBeInTheDocument();
  });

  it("Continue is disabled on Details step when name is empty", () => {
    render(<CampaignWizard {...wizardData} />);
    expect(screen.getByRole("button", { name: /continue/i })).toBeDisabled();
  });

  it("Continue becomes enabled when name is filled", () => {
    render(<CampaignWizard {...wizardData} />);
    fireEvent.change(screen.getByLabelText(/campaign name/i), {
      target: { value: "My campaign" },
    });
    expect(screen.getByRole("button", { name: /continue/i })).not.toBeDisabled();
  });

  it("advancing to step 2 shows Sender step", async () => {
    render(<CampaignWizard {...wizardData} />);
    fireEvent.change(screen.getByLabelText(/campaign name/i), {
      target: { value: "Test" },
    });
    fireEvent.click(screen.getByRole("button", { name: /continue/i }));
    expect(screen.getAllByText(/sender profile/i).length).toBeGreaterThan(0);
  });

  it("Back button on step 2 returns to step 1", async () => {
    render(<CampaignWizard {...wizardData} />);
    fireEvent.change(screen.getByLabelText(/campaign name/i), {
      target: { value: "Test" },
    });
    fireEvent.click(screen.getByRole("button", { name: /continue/i }));
    fireEvent.click(screen.getByRole("button", { name: /back/i }));
    expect(screen.getByLabelText(/campaign name/i)).toBeInTheDocument();
  });

  it("persists draft to localStorage on change", () => {
    render(<CampaignWizard {...wizardData} />);
    fireEvent.change(screen.getByLabelText(/campaign name/i), {
      target: { value: "Draft name" },
    });
    const stored = JSON.parse(localStorageMock.getItem("dispatch:campaign-draft") ?? "{}");
    expect(stored.name).toBe("Draft name");
  });

  it("loads existing draft from localStorage on mount", () => {
    localStorageMock.setItem("dispatch:campaign-draft", JSON.stringify({ ...EMPTY_DRAFT, name: "Restored" }));
    render(<CampaignWizard {...wizardData} />);
    expect((screen.getByLabelText(/campaign name/i) as HTMLInputElement).value).toBe("Restored");
  });
});

// ─── StepDetails ──────────────────────────────────────────────────────────────

describe("StepDetails", () => {
  const base = { draft: { ...EMPTY_DRAFT }, onChange: vi.fn(), onNext: vi.fn() };

  it("renders name and tag inputs", () => {
    render(<StepDetails {...base} />);
    expect(screen.getByLabelText(/campaign name/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/tag/i)).toBeInTheDocument();
  });

  it("calls onChange with name patch", () => {
    render(<StepDetails {...base} />);
    fireEvent.change(screen.getByLabelText(/campaign name/i), { target: { value: "Hi" } });
    expect(base.onChange).toHaveBeenCalledWith({ name: "Hi" });
  });

  it("Continue disabled when name empty", () => {
    render(<StepDetails {...base} />);
    expect(screen.getByRole("button", { name: /continue/i })).toBeDisabled();
  });

  it("Continue enabled when name present", () => {
    render(<StepDetails {...base} draft={{ ...EMPTY_DRAFT, name: "X" }} />);
    expect(screen.getByRole("button", { name: /continue/i })).not.toBeDisabled();
  });
});

// ─── StepSender ───────────────────────────────────────────────────────────────

describe("StepSender", () => {
  const base = {
    draft: { ...EMPTY_DRAFT },
    senderProfiles,
    onChange: vi.fn(),
    onBack: vi.fn(),
    onNext: vi.fn(),
  };

  it("shows radio cards for active sender profiles", () => {
    render(<StepSender {...base} />);
    expect(screen.getAllByRole("radio").length).toBeGreaterThan(0);
  });

  it("Continue disabled when no sender selected", () => {
    render(<StepSender {...base} />);
    expect(screen.getByRole("button", { name: /continue/i })).toBeDisabled();
  });
});

// ─── StepTemplate ─────────────────────────────────────────────────────────────

describe("StepTemplate", () => {
  const base = {
    draft: { ...EMPTY_DRAFT },
    templates: wizardTemplates,
    onChange: vi.fn(),
    onBack: vi.fn(),
    onNext: vi.fn(),
  };

  it("shows template select", () => {
    render(<StepTemplate {...base} />);
    expect(screen.getByLabelText(/template/i)).toBeInTheDocument();
  });

  it("Continue disabled until both template and version are selected", () => {
    render(<StepTemplate {...base} />);
    expect(screen.getByRole("button", { name: /continue/i })).toBeDisabled();
  });
});

// ─── StepAudience ────────────────────────────────────────────────────────────

describe("StepAudience", () => {
  const base = {
    draft: { ...EMPTY_DRAFT },
    segments: mockSegments,
    lists,
    onChange: vi.fn(),
    onBack: vi.fn(),
    onNext: vi.fn(),
  };

  it("renders segment and list radio options", () => {
    render(<StepAudience {...base} />);
    expect(screen.getByRole("radio", { name: /segment/i })).toBeInTheDocument();
    expect(screen.getByRole("radio", { name: /list/i })).toBeInTheDocument();
  });

  it("Continue disabled when no audience selected", () => {
    render(<StepAudience {...base} />);
    expect(screen.getByRole("button", { name: /continue/i })).toBeDisabled();
  });

  it("switching to list shows list select", () => {
    render(<StepAudience {...base} />);
    fireEvent.click(screen.getByRole("radio", { name: /list/i }));
    expect(base.onChange).toHaveBeenCalledWith({ audienceType: "list", audienceId: "" });
  });
});

// ─── StepSchedule ────────────────────────────────────────────────────────────

describe("StepSchedule", () => {
  const base = { draft: { ...EMPTY_DRAFT }, onChange: vi.fn(), onBack: vi.fn(), onNext: vi.fn() };

  it("shows immediate and scheduled radios", () => {
    render(<StepSchedule {...base} />);
    expect(screen.getByRole("radio", { name: /send immediately/i })).toBeInTheDocument();
    expect(screen.getByRole("radio", { name: /schedule for later/i })).toBeInTheDocument();
  });

  it("Continue enabled when immediate is selected", () => {
    render(<StepSchedule {...base} draft={{ ...EMPTY_DRAFT, scheduleType: "immediate" }} />);
    expect(screen.getByRole("button", { name: /continue to review/i })).not.toBeDisabled();
  });

  it("Continue disabled when scheduled but no date", () => {
    render(<StepSchedule {...base} draft={{ ...EMPTY_DRAFT, scheduleType: "scheduled", scheduledAt: "" }} />);
    expect(screen.getByRole("button", { name: /continue to review/i })).toBeDisabled();
  });

  it("shows datetime and timezone inputs when scheduled", () => {
    render(<StepSchedule {...base} draft={{ ...EMPTY_DRAFT, scheduleType: "scheduled" }} />);
    expect(screen.getAllByLabelText(/date and time/i).length).toBeGreaterThan(0);
    expect(screen.getAllByLabelText(/timezone/i).length).toBeGreaterThan(0);
  });
});

// ─── StepReview ───────────────────────────────────────────────────────────────

describe("StepReview", () => {
  const base = {
    draft: filledDraft,
    senderProfiles,
    templates: wizardTemplates,
    segments: mockSegments,
    lists,
    onChange: vi.fn(),
    onBack: vi.fn(),
    onGoToStep: vi.fn(),
    onLaunchSuccess: vi.fn(),
  };

  it("shows campaign name in summary", () => {
    render(<StepReview {...base} />);
    expect(screen.getByText("Test campaign")).toBeInTheDocument();
  });

  it("shows pre-launch checks section", () => {
    render(<StepReview {...base} />);
    expect(screen.getByText(/pre-launch checks/i)).toBeInTheDocument();
  });

  it("Launch campaign button is enabled when no critical checks", () => {
    render(<StepReview {...base} />);
    return waitFor(() => {
      expect(screen.getByRole("button", { name: /launch campaign/i })).not.toBeDisabled();
    });
  });

  it("clicking Launch opens confirm dialog", () => {
    render(<StepReview {...base} />);
    return waitFor(() => {
      const button = screen.getByRole("button", { name: /launch campaign/i });
      expect(button).not.toBeDisabled();
      fireEvent.click(button);
      expect(screen.getByRole("heading", { name: /confirm launch/i })).toBeInTheDocument();
    });
  });

  it("Confirm launch button disabled until campaign name is typed", () => {
    render(<StepReview {...base} />);
    return waitFor(() => {
      const button = screen.getByRole("button", { name: /launch campaign/i });
      expect(button).not.toBeDisabled();
      fireEvent.click(button);
      expect(screen.getByRole("button", { name: /confirm launch/i })).toBeDisabled();
    });
  });

  it("Confirm launch enabled after typing exact campaign name", async () => {
    render(<StepReview {...base} />);
    await waitFor(() => {
      expect(screen.getByRole("button", { name: /launch campaign/i })).not.toBeDisabled();
    });
    fireEvent.click(screen.getByRole("button", { name: /launch campaign/i }));
    fireEvent.change(screen.getByLabelText(/type the campaign name/i), {
      target: { value: "Test campaign" },
    });
    expect(screen.getByRole("button", { name: /confirm launch/i })).not.toBeDisabled();
  });

  it("Edit buttons call onGoToStep with correct step index", () => {
    render(<StepReview {...base} />);
    const editButtons = screen.getAllByRole("button", { name: /edit/i });
    fireEvent.click(editButtons[0]!);
    expect(base.onGoToStep).toHaveBeenCalledWith(0);
  });

  it("shows schedule as Send immediately for immediate type", () => {
    render(<StepReview {...base} />);
    expect(screen.getByText(/send immediately/i)).toBeInTheDocument();
  });

  it("shows tag when present", () => {
    render(<StepReview {...base} />);
    expect(screen.getByText("test-tag")).toBeInTheDocument();
  });

  it("launches campaign and calls onLaunchSuccess on success", async () => {
    render(<StepReview {...base} />);
    await waitFor(() => {
      expect(screen.getByRole("button", { name: /launch campaign/i })).not.toBeDisabled();
    });
    fireEvent.click(screen.getByRole("button", { name: /launch campaign/i }));
    fireEvent.change(screen.getByLabelText(/type the campaign name/i), {
      target: { value: "Test campaign" },
    });
    fireEvent.click(screen.getByRole("button", { name: /confirm launch/i }));

    await waitFor(() => {
      expect(base.onLaunchSuccess).toHaveBeenCalled();
    });
  });
});
