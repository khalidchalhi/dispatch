import { render, screen, fireEvent } from "@testing-library/react";
import { describe, it, expect, vi } from "vitest";
import { ProvisioningWizard } from "@/app/(dashboard)/domains/new/_components/provisioning-wizard";
import { StepLog } from "@/app/(dashboard)/domains/[domainId]/provision/_components/step-log";
import { ProvisioningAudit } from "@/app/(dashboard)/ops/provisioning/_components/provisioning-audit";
import {
  getMockZones,
  getMockProvisioningAttempt,
  getMockProvisioningAudit,
} from "@/app/(dashboard)/domains/_lib/provisioning-queries";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn() }),
}));

vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

vi.mock("@/lib/api/client", () => ({
  clientJson: vi.fn((path: string) => {
    if (path.includes("zones")) {
      return Promise.resolve({
        items: [
          { id: "zone-cf-001", name: "dispatch.internal", provider: "cloudflare" },
          { id: "zone-cf-002", name: "internal.dispatch.io", provider: "cloudflare" },
        ],
      });
    }
    return Promise.resolve({ id: "dom-new", name: "test.example.com" });
  }),
}));

// ─── getMockZones ─────────────────────────────────────────────────────────────

describe("getMockZones", () => {
  it("returns cloudflare zones", () => {
    const zones = getMockZones("cloudflare");
    expect(zones.length).toBeGreaterThanOrEqual(2);
    expect(zones.every((z) => z.provider === "cloudflare")).toBe(true);
  });

  it("returns route53 zones", () => {
    const zones = getMockZones("route53");
    expect(zones.every((z) => z.provider === "route53")).toBe(true);
  });

  it("each zone has id, name, provider", () => {
    for (const z of getMockZones("cloudflare")) {
      expect(z.id).toBeTruthy();
      expect(z.name).toBeTruthy();
    }
  });
});

// ─── getMockProvisioningAttempt ───────────────────────────────────────────────

describe("getMockProvisioningAttempt", () => {
  it("returns completed attempt for dom-003", () => {
    const a = getMockProvisioningAttempt("dom-003");
    expect(a?.status).toBe("completed");
    expect(a?.provider).toBe("cloudflare");
  });

  it("completed attempt has 5 successful steps", () => {
    const a = getMockProvisioningAttempt("dom-003")!;
    expect(a.steps).toHaveLength(5);
    expect(a.steps.every((s) => s.status === "success")).toBe(true);
  });

  it("returns failed attempt for dom-004", () => {
    const a = getMockProvisioningAttempt("dom-004");
    expect(a?.status).toBe("failed");
    expect(a?.failureReason).toBeTruthy();
    expect(a?.failureRemediation).toBeTruthy();
  });

  it("failed attempt has failed step with errorDetail", () => {
    const a = getMockProvisioningAttempt("dom-004")!;
    const failed = a.steps.find((s) => s.status === "failed");
    expect(failed?.errorDetail).toBeTruthy();
  });

  it("returns in_progress attempt for dom-005", () => {
    const a = getMockProvisioningAttempt("dom-005");
    expect(a?.status).toBe("in_progress");
  });

  it("in_progress has a running step", () => {
    const a = getMockProvisioningAttempt("dom-005")!;
    expect(a.steps.some((s) => s.status === "running")).toBe(true);
  });

  it("returns null for unknown domain", () => {
    expect(getMockProvisioningAttempt("unknown")).toBeNull();
  });
});

// ─── getMockProvisioningAudit ─────────────────────────────────────────────────

describe("getMockProvisioningAudit", () => {
  it("returns 5 attempts", () => {
    expect(getMockProvisioningAudit()).toHaveLength(5);
  });

  it("includes all providers", () => {
    const providers = new Set(
      getMockProvisioningAudit().map((a) => a.provider),
    );
    expect(providers.has("cloudflare")).toBe(true);
    expect(providers.has("route53")).toBe(true);
    expect(providers.has("manual")).toBe(true);
  });
});

// ─── ProvisioningWizard ───────────────────────────────────────────────────────

describe("ProvisioningWizard", () => {
  it("renders provider picker on step 1", () => {
    render(<ProvisioningWizard />);
    expect(
      screen.getByText("Choose provisioning method"),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /manual/i })).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /cloudflare/i }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /route 53/i }),
    ).toBeInTheDocument();
  });

  it("shows step 1 of 3 for manual path", () => {
    render(<ProvisioningWizard />);
    fireEvent.click(screen.getByRole("button", { name: /manual/i }));
    expect(screen.getByText(/step 2 of 3/i)).toBeInTheDocument();
  });

  it("shows step 1 of 5 for cloudflare path", () => {
    render(<ProvisioningWizard />);
    fireEvent.click(screen.getByRole("button", { name: /cloudflare/i }));
    expect(screen.getByText(/step 2 of 5/i)).toBeInTheDocument();
  });

  it("navigates to domain name step after provider selection", () => {
    render(<ProvisioningWizard />);
    fireEvent.click(screen.getByRole("button", { name: /manual/i }));
    expect(screen.getByLabelText(/fully-qualified domain name/i)).toBeInTheDocument();
  });

  it("shows error for empty domain name", () => {
    render(<ProvisioningWizard />);
    fireEvent.click(screen.getByRole("button", { name: /manual/i }));
    fireEvent.click(screen.getByRole("button", { name: /next/i }));
    expect(screen.getByRole("alert")).toBeInTheDocument();
  });

  it("shows error for invalid domain name", () => {
    render(<ProvisioningWizard />);
    fireEvent.click(screen.getByRole("button", { name: /manual/i }));
    fireEvent.change(screen.getByLabelText(/fully-qualified domain name/i), {
      target: { value: "not a domain" },
    });
    fireEvent.click(screen.getByRole("button", { name: /next/i }));
    expect(screen.getByRole("alert")).toBeInTheDocument();
  });

  it("valid domain name advances to confirm on manual path", () => {
    render(<ProvisioningWizard />);
    fireEvent.click(screen.getByRole("button", { name: /manual/i }));
    fireEvent.change(screen.getByLabelText(/fully-qualified domain name/i), {
      target: { value: "mail.example.com" },
    });
    fireEvent.click(screen.getByRole("button", { name: /next/i }));
    expect(screen.getByText("Confirm")).toBeInTheDocument();
  });

  it("cloudflare path shows auth step", () => {
    render(<ProvisioningWizard />);
    fireEvent.click(screen.getByRole("button", { name: /cloudflare/i }));
    fireEvent.change(screen.getByLabelText(/fully-qualified domain name/i), {
      target: { value: "mail.example.com" },
    });
    fireEvent.click(screen.getByRole("button", { name: /next/i }));
    expect(screen.getByText(/authorization/i)).toBeInTheDocument();
    expect(screen.getByText(/cloudflare api token/i)).toBeInTheDocument();
  });

  it("cloudflare path shows zone selection after auth", () => {
    render(<ProvisioningWizard />);
    fireEvent.click(screen.getByRole("button", { name: /cloudflare/i }));
    fireEvent.change(screen.getByLabelText(/fully-qualified domain name/i), {
      target: { value: "mail.example.com" },
    });
    fireEvent.click(screen.getByRole("button", { name: /next/i }));
    fireEvent.click(screen.getByRole("button", { name: /next/i }));
    expect(screen.getByText(/select dns zone/i)).toBeInTheDocument();
  });

  it("back button goes to previous step", () => {
    render(<ProvisioningWizard />);
    fireEvent.click(screen.getByRole("button", { name: /manual/i }));
    fireEvent.click(screen.getByRole("button", { name: /back/i }));
    expect(screen.getByText("Choose provisioning method")).toBeInTheDocument();
  });

  it("confirm step shows summary with domain name", () => {
    render(<ProvisioningWizard />);
    fireEvent.click(screen.getByRole("button", { name: /manual/i }));
    fireEvent.change(screen.getByLabelText(/fully-qualified domain name/i), {
      target: { value: "mail.example.com" },
    });
    fireEvent.click(screen.getByRole("button", { name: /next/i }));
    expect(screen.getByText("mail.example.com")).toBeInTheDocument();
  });

  it("manual confirm shows 'Create domain' button", () => {
    render(<ProvisioningWizard />);
    fireEvent.click(screen.getByRole("button", { name: /manual/i }));
    fireEvent.change(screen.getByLabelText(/fully-qualified domain name/i), {
      target: { value: "mail.example.com" },
    });
    fireEvent.click(screen.getByRole("button", { name: /next/i }));
    expect(
      screen.getByRole("button", { name: /create domain/i }),
    ).toBeInTheDocument();
  });

  it("automated confirm shows 'Provision' button", async () => {
    render(<ProvisioningWizard />);
    fireEvent.click(screen.getByRole("button", { name: /cloudflare/i }));
    fireEvent.change(screen.getByLabelText(/fully-qualified domain name/i), {
      target: { value: "mail.example.com" },
    });
    fireEvent.click(screen.getByRole("button", { name: /next/i }));
    fireEvent.click(screen.getByRole("button", { name: /next/i }));
    const zones = await screen.findAllByRole("radio", { hidden: true });
    fireEvent.click(zones[0]!.closest("label")!);
    fireEvent.click(screen.getByRole("button", { name: /next/i }));
    expect(
      screen.getByRole("button", { name: /^provision$/i }),
    ).toBeInTheDocument();
  });
});

// ─── StepLog ──────────────────────────────────────────────────────────────────

describe("StepLog", () => {
  const completed = getMockProvisioningAttempt("dom-003")!;
  const failed = getMockProvisioningAttempt("dom-004")!;
  const inProgress = getMockProvisioningAttempt("dom-005")!;

  it("renders all step labels for completed attempt", () => {
    render(<StepLog initialAttempt={completed} domainId="dom-003" />);
    expect(screen.getByText("Create SES identity")).toBeInTheDocument();
    expect(screen.getByText("Fetch DKIM tokens")).toBeInTheDocument();
    expect(screen.getByText("Write DNS records")).toBeInTheDocument();
    expect(screen.getByText("Verify SES identity")).toBeInTheDocument();
    expect(screen.getByText("Verify DKIM")).toBeInTheDocument();
  });

  it("shows View domain button for completed attempt", () => {
    render(<StepLog initialAttempt={completed} domainId="dom-003" />);
    expect(
      screen.getByRole("link", { name: /view domain/i }),
    ).toBeInTheDocument();
  });

  it("shows Retry and Abandon buttons for failed attempt", () => {
    render(<StepLog initialAttempt={failed} domainId="dom-004" />);
    expect(
      screen.getByRole("button", { name: /retry/i }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /abandon/i }),
    ).toBeInTheDocument();
  });

  it("shows remediation for failed attempt", () => {
    render(<StepLog initialAttempt={failed} domainId="dom-004" />);
    expect(screen.getByText(/suggested remediation/i)).toBeInTheDocument();
    expect(screen.getByText(/Zone:Edit/)).toBeInTheDocument();
  });

  it("expands error detail for failed step", () => {
    render(<StepLog initialAttempt={failed} domainId="dom-004" />);
    const expandBtn = screen
      .getAllByRole("button")
      .find((b) => b.hasAttribute("aria-expanded"));
    expect(expandBtn).toBeDefined();
    fireEvent.click(expandBtn!);
    expect(screen.getByText(/Access denied/i)).toBeInTheDocument();
  });

  it("shows in-progress message for running attempt", () => {
    render(<StepLog initialAttempt={inProgress} domainId="dom-005" />);
    expect(screen.getByText(/provisioning in progress/i)).toBeInTheDocument();
  });

  it("sets up polling for in_progress attempt", () => {
    const setIntervalSpy = vi.spyOn(globalThis, "setInterval");
    render(<StepLog initialAttempt={inProgress} domainId="dom-005" />);
    expect(setIntervalSpy).toHaveBeenCalledWith(
      expect.any(Function),
      3_000,
    );
  });
});

// ─── ProvisioningAudit ────────────────────────────────────────────────────────

describe("ProvisioningAudit", () => {
  const attempts = getMockProvisioningAudit();

  it("renders all domain names", () => {
    render(<ProvisioningAudit attempts={attempts} />);
    expect(screen.getByText("m49.dispatch.internal")).toBeInTheDocument();
    expect(screen.getByText("m48.dispatch.internal")).toBeInTheDocument();
  });

  it("shows completed badge", () => {
    render(<ProvisioningAudit attempts={attempts} />);
    expect(screen.getAllByText("completed").length).toBeGreaterThan(0);
  });

  it("shows failed badge", () => {
    render(<ProvisioningAudit attempts={attempts} />);
    expect(screen.getByText("failed")).toBeInTheDocument();
  });

  it("shows in progress badge", () => {
    render(<ProvisioningAudit attempts={attempts} />);
    expect(screen.getByText("in progress")).toBeInTheDocument();
  });

  it("shows summary counts", () => {
    render(<ProvisioningAudit attempts={attempts} />);
    expect(screen.getByText(/5 total/i)).toBeInTheDocument();
  });

  it("shows failure reason for failed attempt", () => {
    render(<ProvisioningAudit attempts={attempts} />);
    expect(screen.getByText(/dns write failed/i)).toBeInTheDocument();
  });
});
