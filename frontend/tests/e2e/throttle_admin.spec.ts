import { test, expect } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";

test.describe("Domain throughput tab", () => {
  test("throughput tab renders token bucket stats", async ({ page }) => {
    await page.goto("/domains/dom-002?tab=throughput");
    const tokenBucket = page.getByRole("region", { name: "Token bucket status" });
    await expect(tokenBucket.getByText("Rate limit", { exact: true })).toBeVisible();
    await expect(tokenBucket.getByText("Tokens available")).toBeVisible();
    await expect(tokenBucket.getByText("Refill rate")).toBeVisible();
    await expect(tokenBucket.getByText("Denials / min")).toBeVisible();
  });

  test("rate limit value is displayed", async ({ page }) => {
    await page.goto("/domains/dom-002?tab=throughput");
    await expect(page.getByText("300")).toBeVisible();
  });

  test("edit rate limit form is shown", async ({ page }) => {
    await page.goto("/domains/dom-002?tab=throughput");
    await expect(page.getByLabel("Sends per hour")).toBeVisible();
    await expect(page.getByRole("button", { name: /save/i })).toBeVisible();
  });

  test("confirm warning appears for drastic reduction", async ({ page }) => {
    await page.goto("/domains/dom-002?tab=throughput");
    await page.getByLabel("Sends per hour").fill("50");
    await page.getByRole("button", { name: /save/i }).click();
    const warning = page.getByRole("alert").filter({ hasText: /more than 50%/i });
    await expect(warning).toBeVisible();
  });

  test("save button becomes Confirm after drastic reduction attempt", async ({
    page,
  }) => {
    await page.goto("/domains/dom-002?tab=throughput");
    await page.getByLabel("Sends per hour").fill("50");
    await page.getByRole("button", { name: /save/i }).click();
    await expect(page.getByRole("button", { name: /confirm/i })).toBeVisible();
  });

  test("no confirm for moderate reduction", async ({ page }) => {
    await page.goto("/domains/dom-002?tab=throughput");
    await page.getByLabel("Sends per hour").fill("200");
    await page.getByRole("button", { name: /save/i }).click();
    await expect(
      page.getByRole("alert").filter({ hasText: /more than 50%/i }),
    ).not.toBeVisible();
  });

  test("recent denial events table renders", async ({ page }) => {
    await page.goto("/domains/dom-003?tab=throughput");
    await expect(page.getByText("Recent denial events")).toBeVisible();
    await expect(
      page.getByText(/circuit breaker open/i).first(),
    ).toBeVisible();
  });

  test("clean domain shows no denial events message", async ({ page }) => {
    await page.goto("/domains/dom-001?tab=throughput");
    await expect(page.getByText(/no denial events/i)).toBeVisible();
  });

  test("tab nav is visible with all three tabs", async ({ page }) => {
    await page.goto("/domains/dom-002?tab=throughput");
    const tabs = page.getByRole("navigation", { name: "Domain detail tabs" });
    await expect(tabs.getByRole("link", { name: "Overview" })).toBeVisible();
    await expect(tabs.getByRole("link", { name: "DNS records" })).toBeVisible();
    await expect(
      tabs.getByRole("link", { name: "Throughput" }),
    ).toBeVisible();
  });

  test("no accessibility violations on throughput tab", async ({ page }) => {
    await page.goto("/domains/dom-002?tab=throughput");
    await expect(
      page.getByRole("heading", { name: "m48.dispatch.internal", level: 1 }),
    ).toBeVisible();
    const results = await new AxeBuilder({ page }).analyze();
    expect(results.violations).toHaveLength(0);
  });
});

test.describe("Ops queues page", () => {
  test("queues page loads with heading", async ({ page }) => {
    await page.goto("/ops/queues");
    await expect(
      page.getByRole("heading", { name: "Queues" }),
    ).toBeVisible();
  });

  test("shows all three domains", async ({ page }) => {
    await page.goto("/ops/queues");
    await expect(page.getByRole("link", { name: "m47.dispatch.internal" })).toBeVisible();
    await expect(page.getByRole("link", { name: "m48.dispatch.internal" })).toBeVisible();
    await expect(page.getByRole("link", { name: "m49.dispatch.internal" })).toBeVisible();
  });

  test("shows queue names", async ({ page }) => {
    await page.goto("/ops/queues");
    await expect(
      page.getByText("send.m49.dispatch.internal"),
    ).toBeVisible();
  });

  test("shows over-threshold warning", async ({ page }) => {
    await page.goto("/ops/queues");
    await expect(page.getByRole("status")).toBeVisible();
    await expect(page.getByRole("status")).toContainText(/over threshold/i);
  });

  test("search filters domain rows", async ({ page }) => {
    await page.goto("/ops/queues");
    await page.getByRole("searchbox", { name: /search domain/i }).fill("m47");
    await expect(page.getByRole("link", { name: "m47.dispatch.internal" })).toBeVisible();
    await expect(
      page.getByRole("link", { name: "m48.dispatch.internal" }),
    ).not.toBeVisible();
  });

  test("domain link points to throughput tab", async ({ page }) => {
    await page.goto("/ops/queues");
    const link = page.getByRole("link", { name: /m49\.dispatch\.internal/ });
    await expect(link).toHaveAttribute("href", "/domains/dom-003?tab=throughput");
  });

  test("last updated timestamp shown", async ({ page }) => {
    await page.goto("/ops/queues");
    await expect(page.getByText(/last updated/i)).toBeVisible();
  });

  test("no accessibility violations on queues page", async ({ page }) => {
    await page.goto("/ops/queues");
    const results = await new AxeBuilder({ page }).analyze();
    expect(results.violations).toHaveLength(0);
  });
});
