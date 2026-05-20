import type { Page } from "@playwright/test";
import { expect } from "@playwright/test";

export async function startSignIn(page: Page) {
  await page.goto("/login");
  await page.getByLabel("Email").fill("operator@dispatch.internal");
  await page.getByLabel("Password").fill("dispatch-demo-password");
  await page.getByRole("button", { name: "Continue to verification" }).click();
  await expect(page).toHaveURL(/\/mfa(\?|$)/);
}

export async function completeMfa(page: Page, code = "246810") {
  await page.getByLabel("Six-digit code").fill(code);
}

export async function signInToShell(page: Page) {
  await page.goto("/");
  if (await page.getByRole("heading", { name: "Dispatch" }).isVisible()) {
    return;
  }

  await startSignIn(page);
  await completeMfa(page);
  await expect(page).toHaveURL(/\/$/);
  await expect(
    page.getByRole("heading", {
      name: "Dispatch",
    }),
  ).toBeVisible();
}
