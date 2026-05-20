import { defineConfig, devices } from "@playwright/test";

const authStatePath = "tests/e2e/.auth/dev-session.json";
const unauthenticatedSpecs = [
  /.*a11y\.spec\.ts/,
  /.*auth_flow\.spec\.ts/,
  /.*public_unsubscribe\.spec\.ts/,
  /.*smoke\.spec\.ts/,
];

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
    command: "node .next/standalone/server.js",
    url: "http://127.0.0.1:3000",
    cwd: ".",
    env: {
      ...process.env,
      HOSTNAME: "127.0.0.1",
      PORT: "3000",
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
      name: "setup",
      testMatch: /.*\.setup\.ts/,
    },
    {
      name: "chromium-auth",
      testIgnore: /.*\.setup\.ts/,
      testMatch: unauthenticatedSpecs,
      use: {
        ...devices["Desktop Chrome"],
      },
    },
    {
      name: "chromium",
      dependencies: ["setup"],
      testIgnore: [/.*\.setup\.ts/, ...unauthenticatedSpecs],
      use: {
        ...devices["Desktop Chrome"],
        storageState: authStatePath,
      },
    },
  ],
});
