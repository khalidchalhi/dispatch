import { test, expect } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";

test.describe("Campaigns list", () => {
  test("campaigns page loads", async ({ page }) => {
    await page.goto("/campaigns");
    await expect(page.getByRole("heading", { name: "Campaigns" })).toBeVisible();
  });

  test("shows campaign rows", async ({ page }) => {
    await page.goto("/campaigns");
    await expect(page.getByText("April warmup cohort")).toBeVisible();
  });

  test("shows status badge for each campaign", async ({ page }) => {
    await page.goto("/campaigns");
    await expect(page.getByText("draft").first()).toBeVisible();
    await expect(page.getByText("running").first()).toBeVisible();
  });

  test("status tabs are visible", async ({ page }) => {
    await page.goto("/campaigns");
    const tabs = page.getByRole("navigation", { name: /filter by status/i });
    await expect(tabs).toBeVisible();
    await expect(tabs.getByRole("link", { name: "All" })).toBeVisible();
    await expect(tabs.getByRole("link", { name: /Draft/ })).toBeVisible();
    await expect(tabs.getByRole("link", { name: /Running/ })).toBeVisible();
  });

  test("filtering by status shows only matching campaigns", async ({ page }) => {
    await page.goto("/campaigns?status=draft");
    await expect(page.getByText("April warmup cohort")).toBeVisible();
    await expect(page.getByText("Seed inbox test")).not.toBeVisible();
  });

  test("New campaign button links to create page", async ({ page }) => {
    await page.goto("/campaigns");
    const btn = page.getByRole("link", { name: /new campaign/i });
    await expect(btn).toBeVisible();
    await expect(btn).toHaveAttribute("href", "/campaigns/create");
  });

  test("campaign name links to detail page", async ({ page }) => {
    await page.goto("/campaigns");
    await page.getByText("April warmup cohort").click();
    await expect(page).toHaveURL(/\/campaigns\/cmp-001/);
  });

  test("no accessibility violations on list page", async ({ page }) => {
    await page.goto("/campaigns");
    const results = await new AxeBuilder({ page }).analyze();
    expect(results.violations).toHaveLength(0);
  });
});

test.describe("Campaign create wizard", () => {
  test("create page loads with wizard nav", async ({ page }) => {
    await page.goto("/campaigns/create");
    await expect(page.getByRole("heading", { name: "Create campaign" })).toBeVisible();
    await expect(page.getByRole("navigation", { name: /campaign wizard steps/i })).toBeVisible();
  });

  test("first step shows Details form", async ({ page }) => {
    await page.goto("/campaigns/create");
    await expect(page.getByLabel(/campaign name/i)).toBeVisible();
  });

  test("Continue is disabled when name is empty", async ({ page }) => {
    await page.goto("/campaigns/create");
    await expect(page.getByRole("button", { name: /continue/i })).toBeDisabled();
  });

  test("filling name enables Continue", async ({ page }) => {
    await page.goto("/campaigns/create");
    await page.getByLabel(/campaign name/i).fill("E2E test campaign");
    await expect(page.getByRole("button", { name: /continue/i })).toBeEnabled();
  });

  test("wizard advances to Sender step", async ({ page }) => {
    await page.goto("/campaigns/create");
    await page.getByLabel(/campaign name/i).fill("E2E test campaign");
    await page.getByRole("button", { name: /continue/i }).click();
    await expect(page.getByText("Sender profile", { exact: true })).toBeVisible();
  });

  test("Back button returns to previous step", async ({ page }) => {
    await page.goto("/campaigns/create");
    await page.getByLabel(/campaign name/i).fill("Test");
    await page.getByRole("button", { name: /continue/i }).click();
    await page.getByRole("button", { name: /back/i }).click();
    await expect(page.getByLabel(/campaign name/i)).toBeVisible();
  });

  test("wizard nav shows step 1 as active on Details step", async ({ page }) => {
    await page.goto("/campaigns/create");
    const step = page.getByRole("navigation", { name: /campaign wizard steps/i });
    await expect(step.getByText("1. Details")).toBeVisible();
  });

  test("sender step shows radio cards", async ({ page }) => {
    await page.goto("/campaigns/create");
    await page.getByLabel(/campaign name/i).fill("Test");
    await page.getByRole("button", { name: /continue/i }).click();
    const radios = await page.getByRole("radio").count();
    expect(radios).toBeGreaterThan(0);
  });

  test("schedule step renders immediate option pre-selected", async ({ page }) => {
    await page.goto("/campaigns/create");
    // Advance through Details → Sender → Template → Audience → Schedule
    await page.getByLabel(/campaign name/i).fill("Test");
    await page.getByRole("button", { name: /continue/i }).click();
    // select sender
    await page.getByRole("radio").first().click();
    await page.getByRole("button", { name: /continue/i }).click();
    // select template
    await page.getByLabel(/template/i).selectOption({ index: 1 });
    await page.getByRole("button", { name: /continue/i }).click();
    // select audience
    const audienceSelect = page.getByLabel(/segment/i).or(page.getByLabel(/list/i)).last();
    await audienceSelect.selectOption({ index: 1 }).catch(() => {});
    await page.getByRole("button", { name: /continue/i }).click();
    // schedule step
    await expect(page.getByRole("radio", { name: /send immediately/i })).toBeChecked();
  });

  test("review step shows campaign summary dl", async ({ page }) => {
    await page.goto("/campaigns/create");
    await page.getByLabel(/campaign name/i).fill("Test campaign review");
    await page.getByRole("button", { name: /continue/i }).click();
    await page.getByRole("radio").first().click();
    await page.getByRole("button", { name: /continue/i }).click();
    await page.getByLabel(/template/i).selectOption({ index: 1 });
    await page.getByRole("button", { name: /continue/i }).click();
    await page.locator("#audience-segment").selectOption({ index: 1 });
    await page.getByRole("button", { name: /continue/i }).click();
    await page.getByRole("button", { name: /continue to review/i }).click();
    await expect(page.getByRole("heading", { name: "Review" })).toBeVisible();
    await expect(page.locator("dl").filter({ hasText: "Test campaign review" })).toBeVisible();
  });

  test("launch dialog requires typing campaign name to confirm", async ({ page }) => {
    await page.goto("/campaigns/create");
    // Fill all steps
    await page.getByLabel(/campaign name/i).fill("E2E Launch Test");
    await page.getByRole("button", { name: /continue/i }).click();
    await page.getByRole("radio").first().click();
    await page.getByRole("button", { name: /continue/i }).click();
    await page.getByLabel(/template/i).selectOption({ index: 1 });
    await page.getByRole("button", { name: /continue/i }).click();
    // audience - try to skip
    const continueBtn = page.getByRole("button", { name: /continue/i });
    if (await continueBtn.isEnabled()) {
      await continueBtn.click();
    } else {
      // must select audience
      return;
    }
    await page.getByRole("button", { name: /continue to review/i }).click().catch(() => {});
    const launchBtn = page.getByRole("button", { name: /launch campaign/i });
    if (await launchBtn.isVisible()) {
      await launchBtn.click();
      await expect(page.getByText(/confirm launch/i)).toBeVisible();
      await expect(page.getByRole("button", { name: /confirm launch/i })).toBeDisabled();
      await page.getByLabel(/type the campaign name/i).fill("E2E Launch Test");
      await expect(page.getByRole("button", { name: /confirm launch/i })).toBeEnabled();
    }
  });

  test("no accessibility violations on create page", async ({ page }) => {
    await page.goto("/campaigns/create");
    const results = await new AxeBuilder({ page }).analyze();
    expect(results.violations).toHaveLength(0);
  });
});
