import { test, expect } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";

test.describe("Domain reputation view", () => {
  test("reputation page loads", async ({ page }) => {
    await page.goto("/analytics/reputation");
    await expect(
      page.getByRole("heading", { name: "Domain reputation" }),
    ).toBeVisible();
  });

  test("shows freshness indicator", async ({ page }) => {
    await page.goto("/analytics/reputation");
    await expect(page.getByText(/last updated/i)).toBeVisible();
  });

  test("shows threshold legend", async ({ page }) => {
    await page.goto("/analytics/reputation");
    await expect(page.getByText(/0\.75%/)).toBeVisible();
    await expect(page.getByText(/1\.5%/)).toBeVisible();
  });

  test("renders domain table with all columns", async ({ page }) => {
    await page.goto("/analytics/reputation");
    const table = page.getByRole("table", { name: "Domain reputation metrics" });
    await expect(table.getByRole("columnheader", { name: "Bounce%" })).toBeVisible();
    await expect(table.getByRole("columnheader", { name: "Complaint%" })).toBeVisible();
    await expect(table.getByRole("columnheader", { name: "Delivery%" })).toBeVisible();
    await expect(table.getByRole("columnheader", { name: "Breaker" })).toBeVisible();
    await expect(table.getByRole("columnheader", { name: "Warmup stage" })).toBeVisible();
    await expect(table.getByRole("columnheader", { name: "Risk" })).toBeVisible();
  });

  test("shows all 3 domains", async ({ page }) => {
    await page.goto("/analytics/reputation");
    await expect(page.getByText("m48.dispatch.internal")).toBeVisible();
    await expect(page.getByText("m49.dispatch.internal")).toBeVisible();
    await expect(page.getByText("m47.dispatch.internal")).toBeVisible();
  });

  test("critical domain has critical badge", async ({ page }) => {
    await page.goto("/analytics/reputation");
    const table = page.getByRole("table", { name: "Domain reputation metrics" });
    const row = table.getByRole("row").filter({ hasText: "m49.dispatch.internal" });
    await expect(row.getByText("critical", { exact: true })).toBeVisible();
  });

  test("open breaker has open badge", async ({ page }) => {
    await page.goto("/analytics/reputation");
    const table = page.getByRole("table", { name: "Domain reputation metrics" });
    const row = table.getByRole("row").filter({ hasText: "m49.dispatch.internal" });
    await expect(row.getByText("open", { exact: true })).toBeVisible();
  });

  test("domain name links to domain detail page", async ({ page }) => {
    await page.goto("/analytics/reputation");
    const link = page.getByRole("link", { name: /m48\.dispatch\.internal/ });
    await expect(link).toHaveAttribute("href", "/domains/dom-002");
  });

  test("no accessibility violations", async ({ page }) => {
    await page.goto("/analytics/reputation");
    await expect(
      page.getByRole("heading", { name: "Domain reputation", level: 1 }),
    ).toBeVisible();
    const results = await new AxeBuilder({ page }).analyze();
    expect(results.violations).toHaveLength(0);
  });
});
