import { defineConfig, devices } from "@playwright/test";

// Runs against an already running RelayOps stack (API, worker, web). See docs/development.md.
export default defineConfig({
  testDir: "./e2e",
  timeout: Number(process.env.E2E_TIMEOUT_MS ?? 240_000),
  expect: { timeout: 15_000 },
  fullyParallel: false,
  workers: 1,
  retries: 0,
  reporter: [["list"], ["html", { open: "never", outputFolder: "playwright-report" }]],
  use: {
    baseURL: process.env.E2E_BASE_URL ?? "http://localhost:3020",
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  projects: [
    { name: "desktop", use: { ...devices["Desktop Chrome"], viewport: { width: 1440, height: 900 } } },
  ],
});
