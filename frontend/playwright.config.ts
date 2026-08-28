import { defineConfig, devices } from "@playwright/test";
import { readFileSync } from "node:fs";

const rootEnv = readFileSync(new URL("../.env", import.meta.url), "utf8");
const frontendPort =
  process.env.FRONTEND_PORT ?? rootEnv.match(/^FRONTEND_PORT=(\d+)$/m)?.[1];

if (!frontendPort) {
  throw new Error("FRONTEND_PORT is missing from the root .env file");
}

const baseURL = `http://127.0.0.1:${frontendPort}`;

export default defineConfig({
  testDir: "./e2e",
  // The current E2E stack intentionally shares one disposable auth database.
  // Keep tests serial until each worker gets its own backend and database.
  fullyParallel: false,
  forbidOnly: Boolean(process.env.CI),
  retries: process.env.CI ? 2 : 0,
  workers: 1,
  reporter: [
    ["list"],
    ["html", { outputFolder: "playwright-report", open: "never" }],
  ],
  use: {
    baseURL,
    screenshot: "only-on-failure",
    trace: "retain-on-failure",
    video: "retain-on-failure",
  },
  webServer: {
    // The dedicated recipe starts the backend first, uses a disposable account DB,
    // and skips schema codegen so E2E runs cannot dirty committed generated files.
    command: "cd .. && just dev-e2e",
    url: baseURL,
    timeout: 120_000,
    reuseExistingServer: !process.env.CI,
  },
  projects: [
    {
      name: "chromium",
      use: { ...devices["Desktop Chrome"] },
    },
  ],
  outputDir: "test-results",
});
