import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";
import { signInToShell } from "./support/session";

test("renders the domains list with status badges", async ({ page }) => {
  await signInToShell(page);
  await page.goto("/domains");

  await expect(
    page.getByRole("heading", { name: "Domains" }),
  ).toBeVisible();

  await expect(page.getByRole("table", { name: "Sending domains" })).toBeVisible();

  await expect(page.getByText("m47.dispatch.internal")).toBeVisible();
  await expect(page.getByText("m48.dispatch.internal")).toBeVisible();
  await expect(page.getByText("m49.dispatch.internal")).toBeVisible();

  await expect(page.getByText("pending").first()).toBeVisible();
  await expect(page.getByText("verified")).toBeVisible();
  await expect(page.getByText("verifying")).toBeVisible();
});

test("add domain link opens the provisioning wizard", async ({ page }) => {
  await signInToShell(page);
  await page.goto("/domains");

  await page.getByRole("link", { name: "Add domain" }).first().click();

  await expect(page).toHaveURL(/\/domains\/new$/);
  await expect(page.getByRole("heading", { name: /add domain/i })).toBeVisible();
});

test("navigates to domain detail with DNS records", async ({ page }) => {
  await signInToShell(page);
  await page.goto("/domains");

  await page.getByRole("link", { name: "m47.dispatch.internal" }).click();
  await page.getByRole("link", { name: "DNS records" }).click();

  await expect(page).toHaveURL(/\/domains\/dom-001\?tab=dns$/);
  await expect(page.getByRole("heading", { name: "m47.dispatch.internal" })).toBeVisible();

  await expect(page.getByRole("heading", { name: "DNS records" })).toBeVisible();
  const records = page.getByRole("list", { name: "DNS records" });
  await expect(records.getByText("SPF", { exact: true }).first()).toBeVisible();
  await expect(records.getByText("DKIM", { exact: true }).first()).toBeVisible();
  await expect(records.getByText("DMARC", { exact: true }).first()).toBeVisible();
  await expect(records.getByText("MAIL FROM", { exact: true }).first()).toBeVisible();
});

test("domain detail shows verify button for pending domain", async ({
  page,
}) => {
  await signInToShell(page);
  await page.goto("/domains/dom-001?tab=dns");

  await expect(
    page.getByRole("button", { name: "Verify DNS" }),
  ).toBeVisible();
});

test("domain detail shows retire dialog", async ({ page }) => {
  await signInToShell(page);
  await page.goto("/domains/dom-001");

  await page.getByRole("button", { name: "Retire domain" }).click();

  await expect(page.getByRole("dialog")).toBeVisible();
  await expect(
    page.getByRole("heading", { name: "Retire domain" }),
  ).toBeVisible();
});

test("copy-to-clipboard buttons exist on each DNS record", async ({ page }) => {
  await signInToShell(page);
  await page.goto("/domains/dom-001?tab=dns");

  const copyButtons = page.getByRole("button", { name: /copy/i });
  await expect(copyButtons.first()).toBeVisible();
  const count = await copyButtons.count();
  expect(count).toBeGreaterThanOrEqual(5);
});

test("renders the sender profiles list", async ({ page }) => {
  await signInToShell(page);
  await page.goto("/sender-profiles");

  await expect(
    page.getByRole("heading", { name: "Sender profiles", level: 1 }),
  ).toBeVisible();
  await expect(page.getByText("Campaign broadcast")).toBeVisible();
  await expect(
    page.getByRole("link", { name: "m48.dispatch.internal" }).first(),
  ).toBeVisible();
});

test("sender profile detail shows IP pool (read-only)", async ({ page }) => {
  await signInToShell(page);
  await page.goto("/sender-profiles/sp-001");

  await expect(
    page.getByRole("heading", { name: "Campaign broadcast" }),
  ).toBeVisible();
  await expect(
    page.getByRole("heading", { name: "IP pool assignment" }),
  ).toBeVisible();
  await expect(page.getByText("shared-pool-us-east")).toBeVisible();
});

test("has no detected a11y violations on /domains", async ({ page }) => {
  await signInToShell(page);
  await page.goto("/domains");
  await expect(page.getByRole("heading", { name: "Domains", level: 1 })).toBeVisible();

  const results = await new AxeBuilder({ page }).analyze();
  expect(results.violations).toEqual([]);
});

test("has no detected a11y violations on /domains/dom-001", async ({
  page,
}) => {
  await signInToShell(page);
  await page.goto("/domains/dom-001");
  await expect(
    page.getByRole("heading", { name: "m47.dispatch.internal", level: 1 }),
  ).toBeVisible();

  const results = await new AxeBuilder({ page }).analyze();
  expect(results.violations).toEqual([]);
});

test("has no detected a11y violations on /sender-profiles", async ({
  page,
}) => {
  await signInToShell(page);
  await page.goto("/sender-profiles");
  await expect(
    page.getByRole("heading", { name: "Sender profiles", level: 1 }),
  ).toBeVisible();

  const results = await new AxeBuilder({ page }).analyze();
  expect(results.violations).toEqual([]);
});
