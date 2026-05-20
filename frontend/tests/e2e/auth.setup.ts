import { mkdirSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { expect, test as setup } from "@playwright/test";
import { completeMfa, startSignIn } from "./support/session";

const authFile = resolve(__dirname, ".auth", "dev-session.json");

setup("authenticate dev session", async ({ page }) => {
  mkdirSync(dirname(authFile), { recursive: true });

  await startSignIn(page);
  await completeMfa(page);
  await expect(page.getByRole("heading", { name: "Dispatch" })).toBeVisible();
  await page.context().storageState({ path: authFile });
});
