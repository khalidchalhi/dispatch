import { test, expect } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";

test.describe("Analytics overview", () => {
  test("analytics page loads", async ({ page }) => {
    await page.goto("/analytics");
    await expect(
      page.getByRole("heading", { name: "Analytics" }),
    ).toBeVisible();
  });

  test("shows freshness indicator", async ({ page }) => {
    await page.goto("/analytics");
    await expect(page.getByText(/last updated/i)).toBeVisible();
  });

  test("renders all 6 KPI cards", async ({ page }) => {
    await page.goto("/analytics");
    const kpis = page.getByLabel("Key performance indicators");
    await expect(kpis.getByText("Sends today")).toBeVisible();
    await expect(kpis.getByText("7-day sends")).toBeVisible();
    await expect(kpis.getByText("Bounce rate")).toBeVisible();
    await expect(kpis.getByText("Complaint rate")).toBeVisible();
    await expect(kpis.getByText("Open rate")).toBeVisible();
    await expect(kpis.getByText("Click rate")).toBeVisible();
  });

  test("shows top campaigns table", async ({ page }) => {
    await page.goto("/analytics");
    await expect(
      page.getByText(/top campaigns/i),
    ).toBeVisible();
    await expect(
      page.getByText("Q1 product announcement"),
    ).toBeVisible();
  });

  test("campaign name is a link to detail page", async ({ page }) => {
    await page.goto("/analytics");
    const link = page.getByRole("link", { name: "Q1 product announcement" });
    await expect(link).toHaveAttribute("href", "/campaigns/cmp-004");
  });

  test("shows domain health section", async ({ page }) => {
    await page.goto("/analytics");
    await expect(
      page.getByText(/domains needing attention|all domains within/i),
    ).toBeVisible();
  });

  test("shows engagement charts section", async ({ page }) => {
    await page.goto("/analytics");
    await expect(page.getByText(/sends over time/i)).toBeVisible();
    await expect(page.getByText(/open rate by hour/i)).toBeVisible();
  });

  test("no accessibility violations", async ({ page }) => {
    await page.goto("/analytics");
    const results = await new AxeBuilder({ page }).analyze();
    expect(results.violations).toHaveLength(0);
  });
});
