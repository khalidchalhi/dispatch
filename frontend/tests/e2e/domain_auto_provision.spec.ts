import { test, expect } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";

test.describe("Provisioning wizard — new domain", () => {
  test("page loads with heading", async ({ page }) => {
    await page.goto("/domains/new");
    await expect(
      page.getByRole("heading", { name: /add domain/i }),
    ).toBeVisible();
  });

  test("shows provider picker on step 1", async ({ page }) => {
    await page.goto("/domains/new");
    await expect(page.getByText("Choose provisioning method")).toBeVisible();
    await expect(page.getByRole("button", { name: /manual/i })).toBeVisible();
    await expect(
      page.getByRole("button", { name: /cloudflare/i }),
    ).toBeVisible();
    await expect(page.getByRole("button", { name: /route 53/i })).toBeVisible();
  });

  test("manual path: step 2 of 3 after provider selection", async ({
    page,
  }) => {
    await page.goto("/domains/new");
    await page.getByRole("button", { name: /manual/i }).click();
    await expect(page.getByText(/step 2 of 3/i)).toBeVisible();
  });

  test("cloudflare path: step 2 of 5 after provider selection", async ({
    page,
  }) => {
    await page.goto("/domains/new");
    await page.getByRole("button", { name: /cloudflare/i }).click();
    await expect(page.getByText(/step 2 of 5/i)).toBeVisible();
  });

  test("shows FQDN input after provider selection", async ({ page }) => {
    await page.goto("/domains/new");
    await page.getByRole("button", { name: /manual/i }).click();
    await expect(
      page.getByLabel(/fully-qualified domain name/i),
    ).toBeVisible();
  });

  test("shows validation error for empty domain name", async ({ page }) => {
    await page.goto("/domains/new");
    await page.getByRole("button", { name: /manual/i }).click();
    await page.getByRole("button", { name: /next/i }).click();
    await expect(
      page.getByRole("alert").filter({ hasText: /fully-qualified domain name/i }),
    ).toBeVisible();
  });

  test("shows validation error for invalid domain name", async ({ page }) => {
    await page.goto("/domains/new");
    await page.getByRole("button", { name: /manual/i }).click();
    await page.getByLabel(/fully-qualified domain name/i).fill("not a domain");
    await page.getByRole("button", { name: /next/i }).click();
    await expect(
      page.getByRole("alert").filter({ hasText: /valid domain name/i }),
    ).toBeVisible();
  });

  test("back button returns to provider picker", async ({ page }) => {
    await page.goto("/domains/new");
    await page.getByRole("button", { name: /manual/i }).click();
    await page.getByRole("button", { name: /back/i }).click();
    await expect(page.getByText("Choose provisioning method")).toBeVisible();
  });

  test("manual path: valid domain advances to confirm", async ({ page }) => {
    await page.goto("/domains/new");
    await page.getByRole("button", { name: /manual/i }).click();
    await page
      .getByLabel(/fully-qualified domain name/i)
      .fill("mail.example.com");
    await page.getByRole("button", { name: /next/i }).click();
    await expect(page.getByText("Confirm")).toBeVisible();
  });

  test("manual confirm shows domain name in summary", async ({ page }) => {
    await page.goto("/domains/new");
    await page.getByRole("button", { name: /manual/i }).click();
    await page
      .getByLabel(/fully-qualified domain name/i)
      .fill("mail.example.com");
    await page.getByRole("button", { name: /next/i }).click();
    await expect(page.getByText("mail.example.com")).toBeVisible();
  });

  test("manual confirm shows 'Create domain' button", async ({ page }) => {
    await page.goto("/domains/new");
    await page.getByRole("button", { name: /manual/i }).click();
    await page
      .getByLabel(/fully-qualified domain name/i)
      .fill("mail.example.com");
    await page.getByRole("button", { name: /next/i }).click();
    await expect(
      page.getByRole("button", { name: /create domain/i }),
    ).toBeVisible();
  });

  test("cloudflare path shows authorization step", async ({ page }) => {
    await page.goto("/domains/new");
    await page.getByRole("button", { name: /cloudflare/i }).click();
    await page
      .getByLabel(/fully-qualified domain name/i)
      .fill("mail.example.com");
    await page.getByRole("button", { name: /next/i }).click();
    await expect(page.getByText(/authorization/i)).toBeVisible();
    await expect(page.getByText(/cloudflare api token/i)).toBeVisible();
  });

  test("cloudflare path shows zone selection after auth", async ({ page }) => {
    await page.goto("/domains/new");
    await page.getByRole("button", { name: /cloudflare/i }).click();
    await page
      .getByLabel(/fully-qualified domain name/i)
      .fill("mail.example.com");
    await page.getByRole("button", { name: /next/i }).click();
    await page.getByRole("button", { name: /next/i }).click();
    await expect(page.getByText(/select dns zone/i)).toBeVisible();
  });

  test("cloudflare path: selecting zone and clicking Next shows confirm", async ({
    page,
  }) => {
    await page.goto("/domains/new");
    await page.getByRole("button", { name: /cloudflare/i }).click();
    await page
      .getByLabel(/fully-qualified domain name/i)
      .fill("mail.example.com");
    await page.getByRole("button", { name: /next/i }).click();
    await page.getByRole("button", { name: /next/i }).click();
    // select first zone
    const zones = page.locator('input[type="radio"]');
    await zones.first().click({ force: true });
    await page.getByRole("button", { name: /next/i }).click();
    await expect(
      page.getByRole("button", { name: /^provision$/i }),
    ).toBeVisible();
  });

  test("no accessibility violations on wizard step 1", async ({ page }) => {
    await page.goto("/domains/new");
    const results = await new AxeBuilder({ page }).analyze();
    expect(results.violations).toHaveLength(0);
  });
});

test.describe("Step log — provisioning detail", () => {
  test("completed attempt shows all step labels", async ({ page }) => {
    await page.goto("/domains/dom-003/provision");
    await expect(page.getByText("Create SES identity")).toBeVisible();
    await expect(page.getByText("Fetch DKIM tokens")).toBeVisible();
    await expect(page.getByText("Write DNS records")).toBeVisible();
    await expect(page.getByText("Verify SES identity")).toBeVisible();
    await expect(page.getByText("Verify DKIM")).toBeVisible();
  });

  test("completed attempt shows View domain button", async ({ page }) => {
    await page.goto("/domains/dom-003/provision");
    await expect(
      page.getByRole("link", { name: /view domain/i }),
    ).toBeVisible();
  });

  test("failed attempt shows Retry and Abandon buttons", async ({ page }) => {
    await page.goto("/domains/dom-004/provision");
    await expect(
      page.getByRole("button", { name: /retry/i }),
    ).toBeVisible();
    await expect(
      page.getByRole("button", { name: /abandon/i }),
    ).toBeVisible();
  });

  test("failed attempt shows suggested remediation", async ({ page }) => {
    await page.goto("/domains/dom-004/provision");
    await expect(page.getByText(/suggested remediation/i)).toBeVisible();
    await expect(page.getByText(/Zone:Edit/)).toBeVisible();
  });

  test("failed step expand button reveals error detail", async ({ page }) => {
    await page.goto("/domains/dom-004/provision");
    const expandBtn = page.getByRole("button", { name: /show diagnostic/i });
    await expandBtn.click();
    await expect(
      page.locator("#step-detail-write_dns"),
    ).toBeVisible();
    await expect(page.locator("#step-detail-write_dns")).toContainText(
      /Access denied/i,
    );
  });

  test("in-progress attempt shows polling message", async ({ page }) => {
    await page.goto("/domains/dom-005/provision");
    await expect(
      page.getByText(/provisioning in progress/i),
    ).toBeVisible();
  });

  test("completed attempt shows provider badge", async ({ page }) => {
    await page.goto("/domains/dom-003/provision");
    await expect(page.getByText("Cloudflare")).toBeVisible();
  });

  test("breadcrumb links back to domain and domain list", async ({ page }) => {
    await page.goto("/domains/dom-003/provision");
    await expect(
      page.getByRole("link", { name: /domains/i }).first(),
    ).toBeVisible();
  });

  test("no accessibility violations on completed provision page", async ({
    page,
  }) => {
    await page.goto("/domains/dom-003/provision");
    await expect(
      page.getByRole("heading", { name: "Provisioning", level: 1 }),
    ).toBeVisible();
    const results = await new AxeBuilder({ page }).analyze();
    expect(results.violations).toHaveLength(0);
  });
});

test.describe("Provisioning audit log", () => {
  test("page loads with heading", async ({ page }) => {
    await page.goto("/ops/provisioning");
    await expect(
      page.getByRole("heading", { name: /provisioning/i }),
    ).toBeVisible();
  });

  test("shows domain names in audit table", async ({ page }) => {
    await page.goto("/ops/provisioning");
    await expect(page.getByText("m49.dispatch.internal")).toBeVisible();
    await expect(page.getByText("m48.dispatch.internal")).toBeVisible();
  });

  test("shows completed badge", async ({ page }) => {
    await page.goto("/ops/provisioning");
    const badges = page.getByText("completed");
    await expect(badges.first()).toBeVisible();
  });

  test("shows failed badge", async ({ page }) => {
    await page.goto("/ops/provisioning");
    await expect(page.getByText("failed").first()).toBeVisible();
  });

  test("shows in progress badge", async ({ page }) => {
    await page.goto("/ops/provisioning");
    await expect(page.getByText("in progress")).toBeVisible();
  });

  test("shows failure reason for failed attempt", async ({ page }) => {
    await page.goto("/ops/provisioning");
    await expect(page.getByText(/dns write failed/i)).toBeVisible();
  });

  test("shows summary count with 5 total", async ({ page }) => {
    await page.goto("/ops/provisioning");
    await expect(page.getByText(/5 total/i)).toBeVisible();
  });

  test("Step log links exist for automated attempts", async ({ page }) => {
    await page.goto("/ops/provisioning");
    const stepLinks = page.getByRole("link", { name: /step log/i });
    await expect(stepLinks.first()).toBeVisible();
  });

  test("no accessibility violations", async ({ page }) => {
    await page.goto("/ops/provisioning");
    await expect(
      page.getByRole("heading", { name: /provisioning/i, level: 1 }),
    ).toBeVisible();
    const results = await new AxeBuilder({ page }).analyze();
    expect(results.violations).toHaveLength(0);
  });
});
