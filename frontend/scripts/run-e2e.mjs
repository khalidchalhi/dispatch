import { spawnSync } from "node:child_process";

const command = process.execPath;
const pnpmBootstrapArgs = process.env.npm_execpath
  ? [process.env.npm_execpath]
  : [process.platform === "win32" ? "corepack.cmd" : "corepack", "pnpm"];
const sharedEnv = {
  ...process.env,
  DISPATCH_WEB_APP_ORIGIN: "http://127.0.0.1:3000",
  DISPATCH_WEB_ENABLE_DEV_SESSION: "true",
  DISPATCH_WEB_SESSION_SECRET: "dispatch-web-playwright-session-secret",
};

for (const args of [["build"], ["exec", "playwright", "test"]]) {
  const result = spawnSync(command, [...pnpmBootstrapArgs, ...args], {
    cwd: process.cwd(),
    env: sharedEnv,
    stdio: "inherit",
  });

  if (result.error) {
    throw result.error;
  }

  if (result.status !== 0) {
    process.exit(result.status ?? 1);
  }
}
