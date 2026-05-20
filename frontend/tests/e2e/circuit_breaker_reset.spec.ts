import { test, expect } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";

test.describe("Circuit breaker console", () => {
  test("page loads with heading", async ({ page }) => {
    await page.goto("/ops/circuit-breakers");
    await expect(
      page.getByRole("heading", { name: "Circuit breakers" }),
    ).toBeVisible();
  });

  test("shows all four scope headings", async ({ page }) => {
    await page.goto("/ops/circuit-breakers");
    await expect(page.getByRole("heading", { name: "Domain" })).toBeVisible();
    await expect(page.getByRole("heading", { name: "IP pool" })).toBeVisible();
    await expect(page.getByRole("heading", { name: "Sender profile" })).toBeVisible();
    await expect(page.getByRole("heading", { name: "Account" })).toBeVisible();
  });

  test("shows open count status", async ({ page }) => {
    await page.goto("/ops/circuit-breakers");
    await expect(page.getByRole("status")).toBeVisible();
    await expect(page.getByRole("status")).toContainText(/3 open/i);
  });

  test("m49.dispatch.internal shows open badge", async ({ page }) => {
    await page.goto("/ops/circuit-breakers");
    const row = page.getByRole("row", {}).filter({ hasText: "m49.dispatch.internal" });
    await expect(row.getByText("open")).toBeVisible();
  });

  test("Reset buttons exist for open breakers", async ({ page }) => {
    await page.goto("/ops/circuit-breakers");
    const resets = page.getByRole("button", { name: /^reset$/i });
    await expect(resets).toHaveCount(3);
  });

  test("Open only filter hides closed entries", async ({ page }) => {
    await page.goto("/ops/circuit-breakers");
    await page.getByRole("button", { name: /open only/i }).click();
    await expect(page.getByText("m47.dispatch.internal")).not.toBeVisible();
    await expect(page.getByText("m49.dispatch.internal")).toBeVisible();
  });

  test("Last 24h filter shows recent trips", async ({ page }) => {
    await page.goto("/ops/circuit-breakers");
    await page.getByRole("button", { name: /last 24h/i }).click();
    await expect(page.getByRole("link", { name: "m49.dispatch.internal" })).toBeVisible();
  });

  test("expand row shows trip timeline", async ({ page }) => {
    await page.goto("/ops/circuit-breakers");
    await page.getByRole("button", { name: /expand timeline/i }).first().click();
    await expect(page.getByText("Trip timeline")).toBeVisible();
  });

  test("Reset button opens dialog with entity name", async ({ page }) => {
    await page.goto("/ops/circuit-breakers");
    await page.getByRole("button", { name: /^reset$/i }).first().click();
    await expect(page.getByRole("dialog")).toBeVisible();
    await expect(page.getByText("Reset circuit breaker")).toBeVisible();
  });

  test("reset disabled without justification", async ({ page }) => {
    await page.goto("/ops/circuit-breakers");
    await page.getByRole("button", { name: /^reset$/i }).first().click();
    await expect(
      page.getByRole("button", { name: /reset breaker/i }),
    ).toBeDisabled();
  });

  test("reset enabled with long enough justification", async ({ page }) => {
    await page.goto("/ops/circuit-breakers");
    await page.getByRole("button", { name: /^reset$/i }).first().click();
    await page.getByLabel(/justification/i).fill(
      "Bounce rate dropped back below threshold after cleanup.",
    );
    await expect(
      page.getByRole("button", { name: /reset breaker/i }),
    ).not.toBeDisabled();
  });

  test("cancel closes the dialog", async ({ page }) => {
    await page.goto("/ops/circuit-breakers");
    await page.getByRole("button", { name: /^reset$/i }).first().click();
    await page.getByRole("button", { name: /cancel/i }).click();
    await expect(page.getByRole("dialog")).not.toBeVisible();
  });

  test("no accessibility violations", async ({ page }) => {
    await page.goto("/ops/circuit-breakers");
    await expect(
      page.getByRole("heading", { name: "Circuit breakers", level: 1 }),
    ).toBeVisible();
    const results = await new AxeBuilder({ page }).analyze();
    expect(results.violations).toHaveLength(0);
  });
});

test.describe("CircuitBreakerBadge on domain detail", () => {
  test("domain with open breaker shows badge link to console", async ({
    page,
  }) => {
    await page.goto("/domains/dom-003");
    const link = page.getByRole("link", { name: /circuit breaker open/i });
    await expect(link).toHaveAttribute(
      "href",
      "/ops/circuit-breakers?scope=domain&entity=dom-003",
    );
  });

  test("domain with closed breaker shows closed badge", async ({ page }) => {
    await page.goto("/domains/dom-002");
    const link = page.getByRole("link", { name: /circuit breaker closed/i });
    await expect(link).toBeVisible();
  });
});

test.describe("CircuitBreakerBadge on sender profile detail", () => {
  test("sp-002 shows open circuit breaker badge", async ({ page }) => {
    await page.goto("/sender-profiles/sp-002");
    const link = page.getByRole("link", { name: /circuit breaker open/i });
    await expect(link).toHaveAttribute(
      "href",
      "/ops/circuit-breakers?scope=sender_profile&entity=sp-002",
    );
  });
});

test.describe("CircuitBreakerBadge on campaign monitoring", () => {
  test("campaign on open-breaker domain shows badge", async ({ page }) => {
    await page.goto("/campaigns/cmp-003");
    const link = page.getByRole("link", { name: /circuit breaker open/i });
    await expect(link).toBeVisible();
  });
});
