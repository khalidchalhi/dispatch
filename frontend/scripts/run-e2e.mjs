import { spawnSync } from "node:child_process";
import { cpSync, existsSync, mkdirSync, rmSync } from "node:fs";
import { join } from "node:path";

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

function copyStandaloneAssets() {
  const staticSource = join(process.cwd(), ".next", "static");
  const staticTarget = join(process.cwd(), ".next", "standalone", ".next", "static");
  const publicSource = join(process.cwd(), "public");
  const publicTarget = join(process.cwd(), ".next", "standalone", "public");

  if (existsSync(staticSource)) {
    rmSync(staticTarget, { recursive: true, force: true });
    mkdirSync(join(process.cwd(), ".next", "standalone", ".next"), { recursive: true });
    cpSync(staticSource, staticTarget, { recursive: true });
  }

  if (existsSync(publicSource)) {
    rmSync(publicTarget, { recursive: true, force: true });
    cpSync(publicSource, publicTarget, { recursive: true });
  }
}

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

  if (args[0] === "build") {
    copyStandaloneAssets();
  }
}
