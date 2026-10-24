import { expect, test, type Page } from "@playwright/test";
import { publishedVenue, resetRateLimits } from "./helpers";

test.beforeEach(async () => resetRateLimits());

/**
 * What a person on a mid-range phone and a slow connection sees while a page loads. The page must not jump: the front door, a demo
 * venue and the survey a guest scans are the pages strangers land on first. The limit is the 0.1 that web.dev calls good; two of
 * these pages were at 0.42 and 0.72 before their loading states reserved their space.
 */
async function shiftsWhileLoading(page: Page, address: string, settle: string): Promise<{ total: number; seen: string[] }> {
  const cdp = await page.context().newCDPSession(page);
  await cdp.send("Emulation.setCPUThrottlingRate", { rate: 4 });
  await cdp.send("Network.enable");
  await cdp.send("Network.emulateNetworkConditions", { offline: false, latency: 150, downloadThroughput: (1.6 * 1024 * 1024) / 8, uploadThroughput: (750 * 1024) / 8 });
  await page.addInitScript(() => {
    const w = window as unknown as { __shifts: { v: number; where: string }[] };
    w.__shifts = [];
    new PerformanceObserver((list) => {
      for (const e of list.getEntries() as unknown as { value: number; hadRecentInput: boolean; sources: { node?: Element }[] }[]) {
        if (e.hadRecentInput) continue;
        const node = e.sources[0]?.node;
        w.__shifts.push({ v: e.value, where: node && node.nodeType === 1 ? `${node.tagName}.${node.className}` : "text" });
      }
    }).observe({ type: "layout-shift", buffered: true });
  });
  await page.goto(address);
  await expect(page.locator(settle).first()).toBeVisible({ timeout: 30_000 });
  await page.waitForTimeout(1500); // late arrivals: a font, a second request
  const shifts = await page.evaluate(() => (window as unknown as { __shifts: { v: number; where: string }[] }).__shifts);
  return { total: shifts.reduce((a, s) => a + s.v, 0), seen: shifts.map((s) => `${s.where} ${s.v.toFixed(3)}`) };
}

test("the front door does not jump while the demo venues load", async ({ page }) => {
  test.setTimeout(90_000);
  const { total, seen } = await shiftsWhileLoading(page, "/", '[data-testid="venue-card"]');
  expect(total, seen.join("; ")).toBeLessThanOrEqual(0.1);
});

test("a demo venue does not jump while it and its tab load", async ({ page }) => {
  test.setTimeout(90_000);
  const venues = (await (await page.request.get("/api/v1/public/demo")).json()) as { slug: string }[];
  expect(venues.length, "no demo venue is built").toBeGreaterThan(0);
  const { total, seen } = await shiftsWhileLoading(page, `/try/${venues[0]!.slug}?tab=sound`, '[data-testid="act"], [data-testid="not-ready"]');
  expect(total, seen.join("; ")).toBeLessThanOrEqual(0.1);
});

test("the survey a guest scans does not jump while it loads", async ({ page, request }) => {
  test.setTimeout(90_000);
  const venue = await publishedVenue(request);
  const { total, seen } = await shiftsWhileLoading(page, `/s/${venue.token}`, "h1");
  expect(total, seen.join("; ")).toBeLessThanOrEqual(0.1);
});
