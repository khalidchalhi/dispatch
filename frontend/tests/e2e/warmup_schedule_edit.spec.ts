import { test, expect } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";

test.describe("Warmup tab — dom-002 (in-progress)", () => {
  test("warmup tab loads with progress bar", async ({ page }) => {
    await page.goto("/domains/dom-002?tab=warmup");
    await expect(page.getByRole("progressbar")).toBeVisible();
  });

  test("shows day 23 of 30", async ({ page }) => {
    await page.goto("/domains/dom-002?tab=warmup");
    await expect(page.getByText(/day 23 of 30/i)).toBeVisible();
  });

  test("shows today cap and sends", async ({ page }) => {
    await page.goto("/domains/dom-002?tab=warmup");
    await expect(page.getByText(/today.s cap/i)).toBeVisible();
    await expect(page.getByText(/sends today/i)).toBeVisible();
  });

  test("shows scheduled graduation", async ({ page }) => {
    await page.goto("/domains/dom-002?tab=warmup");
    await expect(page.getByText(/scheduled graduation/i)).toBeVisible();
  });

  test("shows upcoming schedule table", async ({ page }) => {
    await page.goto("/domains/dom-002?tab=warmup");
    await expect(page.getByText(/upcoming schedule/i)).toBeVisible();
  });

  test("Extend by 7 days button is present", async ({ page }) => {
    await page.goto("/domains/dom-002?tab=warmup");
    await expect(
      page.getByRole("button", { name: /extend by 7 days/i }),
    ).toBeVisible();
  });

  test("Edit schedule opens preset picker", async ({ page }) => {
    await page.goto("/domains/dom-002?tab=warmup");
    await page.getByRole("button", { name: /edit schedule/i }).click();
    await expect(page.getByText(/choose a preset schedule/i)).toBeVisible();
    await expect(
      page.getByRole("button", { name: /conservative/i }),
    ).toBeVisible();
    await expect(
      page.getByRole("button", { name: /aggressive/i }),
    ).toBeVisible();
  });

  test("cancel closes editor", async ({ page }) => {
    await page.goto("/domains/dom-002?tab=warmup");
    await page.getByRole("button", { name: /edit schedule/i }).click();
    await page.getByRole("button", { name: /cancel/i }).click();
    await expect(
      page.getByText(/choose a preset schedule/i),
    ).not.toBeVisible();
  });

  test("no accessibility violations on warmup tab", async ({ page }) => {
    await page.goto("/domains/dom-002?tab=warmup");
    const results = await new AxeBuilder({ page }).analyze();
    expect(results.violations).toHaveLength(0);
  });
});

test.describe("Warmup tab — dom-001 (not started, 5x safety)", () => {
  test("shows 'Not yet started'", async ({ page }) => {
    await page.goto("/domains/dom-001?tab=warmup");
    await expect(page.getByText(/not yet started/i)).toBeVisible();
  });

  test("aggressive preset triggers 5x warning", async ({ page }) => {
    await page.goto("/domains/dom-001?tab=warmup");
    await page.getByRole("button", { name: /edit schedule/i }).click();
    await page.getByRole("button", { name: /aggressive/i }).click();
    await expect(
      page.getByRole("alert").filter({ hasText: /aggressive schedule warning/i }),
    ).toBeVisible();
  });

  test("save disabled without confirm", async ({ page }) => {
    await page.goto("/domains/dom-001?tab=warmup");
    await page.getByRole("button", { name: /edit schedule/i }).click();
    await page.getByRole("button", { name: /aggressive/i }).click();
    await expect(
      page.getByRole("button", { name: /save schedule/i }),
    ).toBeDisabled();
  });

  test("save enabled after checking confirm checkbox", async ({ page }) => {
    await page.goto("/domains/dom-001?tab=warmup");
    await page.getByRole("button", { name: /edit schedule/i }).click();
    await page.getByRole("button", { name: /aggressive/i }).click();
    await page
      .getByRole("checkbox", { name: /understand the risk/i })
      .check();
    await expect(
      page.getByRole("button", { name: /save schedule/i }),
    ).not.toBeDisabled();
  });

  test("standard preset does not trigger warning", async ({ page }) => {
    await page.goto("/domains/dom-001?tab=warmup");
    await page.getByRole("button", { name: /edit schedule/i }).click();
    await page.getByRole("button", { name: /^standard/i }).click();
    await expect(
      page.getByText(/aggressive schedule warning/i),
    ).not.toBeVisible();
    await expect(
      page.getByRole("button", { name: /save schedule/i }),
    ).not.toBeDisabled();
  });
});

test.describe("Warmup tab — dom-003 (overpacing)", () => {
  test("shows overpacing alert", async ({ page }) => {
    await page.goto("/domains/dom-003?tab=warmup");
    await expect(
      page.getByRole("alert").filter({ hasText: /volume exceeding cap/i }),
    ).toBeVisible();
  });
});

test.describe("Reputation tab — connected (dom-002)", () => {
  test("shows 'As of' timestamp", async ({ page }) => {
    await page.goto("/domains/dom-002?tab=reputation");
    await expect(page.getByText(/as of/i)).toBeVisible();
  });

  test("shows metric cards", async ({ page }) => {
    await page.goto("/domains/dom-002?tab=reputation");
    await expect(page.getByText(/^spam rate$/i).first()).toBeVisible();
    await expect(page.getByText(/^domain reputation$/i)).toBeVisible();
    await expect(page.getByText(/^spf pass$/i).first()).toBeVisible();
    await expect(page.getByText(/^dkim pass$/i).first()).toBeVisible();
  });

  test("shows 7-day history table", async ({ page }) => {
    await page.goto("/domains/dom-002?tab=reputation");
    await expect(page.getByText(/last 7 days/i)).toBeVisible();
  });

  test("shows Open Postmaster link", async ({ page }) => {
    await page.goto("/domains/dom-002?tab=reputation");
    await expect(
      page.getByRole("link", { name: /open postmaster/i }).first(),
    ).toBeVisible();
  });

  test("no accessibility violations on reputation tab (connected)", async ({
    page,
  }) => {
    await page.goto("/domains/dom-002?tab=reputation");
    await expect(
      page.getByRole("heading", { name: "m48.dispatch.internal", level: 1 }),
    ).toBeVisible();
    const results = await new AxeBuilder({ page }).analyze();
    expect(results.violations).toHaveLength(0);
  });
});

test.describe("Reputation tab — disconnected (dom-001)", () => {
  test("shows connect CTA", async ({ page }) => {
    await page.goto("/domains/dom-001?tab=reputation");
    await expect(
      page.getByText(/google postmaster not connected/i),
    ).toBeVisible();
    await expect(
      page.getByRole("button", { name: /connect postmaster/i }),
    ).toBeVisible();
  });

  test("no accessibility violations on disconnected reputation tab", async ({
    page,
  }) => {
    await page.goto("/domains/dom-001?tab=reputation");
    await expect(
      page.getByRole("heading", { name: "m47.dispatch.internal", level: 1 }),
    ).toBeVisible();
    const results = await new AxeBuilder({ page }).analyze();
    expect(results.violations).toHaveLength(0);
  });
});

test.describe("Analytics — warming domains widget", () => {
  test("warming domains widget is visible", async ({ page }) => {
    await page.goto("/analytics");
    await expect(page.getByText(/domains in warmup/i)).toBeVisible();
  });

  test("shows all 3 warming domain names", async ({ page }) => {
    await page.goto("/analytics");
    const warmupPanel = page.locator("section").filter({
      has: page.getByRole("heading", { name: "Domains in warmup" }),
    });
    await expect(warmupPanel.getByRole("link", { name: "m47.dispatch.internal" })).toBeVisible();
    await expect(warmupPanel.getByRole("link", { name: "m48.dispatch.internal" })).toBeVisible();
    await expect(warmupPanel.getByRole("link", { name: "m49.dispatch.internal" })).toBeVisible();
  });

  test("domain name links to warmup tab", async ({ page }) => {
    await page.goto("/analytics");
    const warmupPanel = page.locator("section").filter({
      has: page.getByRole("heading", { name: "Domains in warmup" }),
    });
    const link = warmupPanel.getByRole("link", { name: "m48.dispatch.internal" });
    await expect(link).toHaveAttribute(
      "href",
      "/domains/dom-002?tab=warmup",
    );
  });
});
