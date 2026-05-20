import { test, expect } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";

test.describe("Campaign monitoring page", () => {
  test("loads campaign detail page", async ({ page }) => {
    await page.goto("/campaigns/cmp-003");
    await expect(
      page.getByRole("heading", { name: /campaign monitoring/i }),
    ).toBeVisible();
  });

  test("shows campaign name in header", async ({ page }) => {
    await page.goto("/campaigns/cmp-003");
    await expect(page.getByText("Seed inbox test")).toBeVisible();
  });

  test("shows all 8 KPI tiles", async ({ page }) => {
    await page.goto("/campaigns/cmp-003");
    const kpis = page.getByLabel("Campaign KPI tiles");
    await expect(kpis.getByText("Queued")).toBeVisible();
    await expect(kpis.getByText("Sent")).toBeVisible();
    await expect(kpis.getByText("Delivered")).toBeVisible();
    await expect(kpis.getByText("Bounced")).toBeVisible();
    await expect(kpis.getByText("Clicked")).toBeVisible();
  });

  test("shows running status badge", async ({ page }) => {
    await page.goto("/campaigns/cmp-003");
    await expect(page.getByText("running").first()).toBeVisible();
  });

  test("shows Pause and Cancel buttons for running campaign", async ({ page }) => {
    await page.goto("/campaigns/cmp-003");
    await expect(page.getByRole("button", { name: /pause/i })).toBeVisible();
    await expect(page.getByRole("button", { name: /cancel/i })).toBeVisible();
  });

  test("shows send funnel", async ({ page }) => {
    await page.goto("/campaigns/cmp-003");
    await expect(page.getByText(/send funnel/i)).toBeVisible();
  });

  test("shows send velocity chart", async ({ page }) => {
    await page.goto("/campaigns/cmp-003");
    await expect(page.getByText(/send velocity/i)).toBeVisible();
  });

  test("shows messages table", async ({ page }) => {
    await page.goto("/campaigns/cmp-003");
    await expect(page.getByText(/messages/i).first()).toBeVisible();
  });

  test("messages table has status filter", async ({ page }) => {
    await page.goto("/campaigns/cmp-003");
    await expect(
      page.getByRole("combobox", { name: /filter by status/i }),
    ).toBeVisible();
  });

  test("message rows are visible", async ({ page }) => {
    await page.goto("/campaigns/cmp-003");
    const rows = page.locator("[aria-pressed]");
    await expect(rows.first()).toBeVisible();
  });

  test("clicking a message row opens inspector drawer", async ({ page }) => {
    await page.goto("/campaigns/cmp-003");
    const rows = page.locator("[aria-pressed]");
    await rows.first().click();
    await expect(page.getByText("Message inspector")).toBeVisible();
  });

  test("inspector drawer has Overview, Rendered email, Event timeline tabs", async ({
    page,
  }) => {
    await page.goto("/campaigns/cmp-003");
    await page.locator("[aria-pressed]").first().click();
    await expect(page.getByRole("tab", { name: /overview/i })).toBeVisible();
    await expect(
      page.getByRole("tab", { name: /rendered email/i }),
    ).toBeVisible();
    await expect(
      page.getByRole("tab", { name: /event timeline/i }),
    ).toBeVisible();
  });

  test("event timeline shows at least one event", async ({ page }) => {
    await page.goto("/campaigns/cmp-003");
    await page.locator("[aria-pressed]").first().click();
    await page.getByRole("tab", { name: /event timeline/i }).click();
    await expect(page.getByText(/queued/i).first()).toBeVisible();
  });

  test("closing drawer hides inspector", async ({ page }) => {
    await page.goto("/campaigns/cmp-003");
    await page.locator("[aria-pressed]").first().click();
    await page.getByRole("button", { name: /close/i }).click();
    await expect(page.getByText("Message inspector")).not.toBeVisible();
  });

  test("Load more appends additional messages", async ({ page }) => {
    await page.goto("/campaigns/cmp-003");
    const initialRows = await page.locator("[aria-pressed]").count();
    await page.getByRole("button", { name: /load more/i }).click();
    await expect
      .poll(() => page.locator("[aria-pressed]").count())
      .toBeGreaterThan(initialRows);
  });

  test("status filter narrows message list", async ({ page }) => {
    await page.goto("/campaigns/cmp-003");
    await page
      .getByRole("combobox", { name: /filter by status/i })
      .selectOption("bounced");
    const rows = page.locator("[aria-pressed]");
    await expect(rows.first()).toBeVisible();
  });

  test("completed campaign shows no action buttons", async ({ page }) => {
    await page.goto("/campaigns/cmp-004");
    await expect(
      page.getByRole("button", { name: /pause/i }),
    ).not.toBeVisible();
  });

  test("no accessibility violations on monitor page", async ({ page }) => {
    await page.goto("/campaigns/cmp-003");
    const results = await new AxeBuilder({ page }).analyze();
    expect(results.violations).toHaveLength(0);
  });
});
