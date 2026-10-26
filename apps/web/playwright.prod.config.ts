import { defineConfig } from "@playwright/test";

// A deployed copy, reached only through its public address: no local servers and no database. Used with e2e/prodsmoke.spec.ts.
const WEB = process.env.NIGIWAI_WEB_URL;
if (!WEB) throw new Error("set NIGIWAI_WEB_URL to the deployed address, for example https://nigiwai.example.com");

export default defineConfig({
  testDir: "./e2e",
  testMatch: /prodsmoke\.spec\.ts/,
  outputDir: "./test-results-prod",
  timeout: 90_000,
  expect: { timeout: 15_000 },
  fullyParallel: false,
  workers: 1,
  reporter: [["list"]],
  use: { baseURL: WEB, channel: "chrome", trace: "retain-on-failure", screenshot: "only-on-failure" },
  projects: [{ name: "desktop", use: { viewport: { width: 1440, height: 900 }, channel: "chrome" } }],
});
