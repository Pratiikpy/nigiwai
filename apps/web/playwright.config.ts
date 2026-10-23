import { defineConfig, devices } from "@playwright/test";

const WEB = process.env.NIGIWAI_WEB_URL ?? "http://127.0.0.1:3000";

// The stack under test is the real one: Postgres and Redis from `just up`, the API, and the built web app. Real Chrome is
// used (no browser download). Reuse running servers when they are up; otherwise start them.
export default defineConfig({
  testDir: "./e2e",
  outputDir: "./test-results",
  timeout: 60_000,
  expect: { timeout: 10_000 },
  fullyParallel: false,
  workers: 1,
  reporter: [["list"], ["html", { open: "never", outputFolder: "playwright-report" }]],
  use: {
    baseURL: WEB,
    channel: "chrome",
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  projects: [
    { name: "phone", use: { ...devices["Pixel 7"], channel: "chrome" } },
    { name: "desktop", use: { viewport: { width: 1440, height: 900 }, channel: "chrome" } },
  ],
  webServer: [
    {
      command: "uv run uvicorn nigiwai_api.app:create_app --factory --host 127.0.0.1 --port 8000",
      cwd: "../..",
      url: "http://127.0.0.1:8000/readyz",
      reuseExistingServer: true,
      timeout: 60_000,
    },
    {
      command: "pnpm start",
      url: `${WEB}/login`,
      reuseExistingServer: true,
      timeout: 60_000,
      env: { NIGIWAI_API_ORIGIN: "http://127.0.0.1:8000" },
    },
  ],
});
