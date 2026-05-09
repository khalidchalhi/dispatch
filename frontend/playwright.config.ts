import { defineConfig, devices } from "@playwright/test";

export default defineConfig({
  testDir: "./tests/e2e",
  fullyParallel: false,
  retries: process.env.CI ? 2 : 0,
  reporter: "line",
  workers: process.env.CI ? 2 : 1,
  use: {
    baseURL: "http://127.0.0.1:3000",
    trace: "on-first-retry",
  },
  webServer: {
    command: "corepack pnpm exec next start --hostname 127.0.0.1 --port 3000",
    url: "http://127.0.0.1:3000",
    cwd: ".",
    env: {
      ...process.env,
      DISPATCH_WEB_APP_ORIGIN: "http://127.0.0.1:3000",
      DISPATCH_WEB_ENABLE_DEV_SESSION: "true",
      DISPATCH_WEB_SESSION_SECRET: "dispatch-web-playwright-session-secret",
    },
    reuseExistingServer: !process.env.CI,
    stdout: "pipe",
    stderr: "pipe",
    timeout: 120000,
  },
  projects: [
    {
      name: "chromium",
      use: {
        ...devices["Desktop Chrome"],
      },
    },
  ],
});
