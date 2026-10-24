import { expect, test } from "@playwright/test";
import { openAllWeek, plantCrowd, plantPool, plantWeek, publishedVenue, resetRateLimits, shot, signIn, sql, watch } from "./helpers";

// Every owner page at 320 CSS pixels wide, the narrowest width WCAG asks content to reflow to (1.4.10), with real data on it:
// nothing may spill sideways and cause a horizontal scroll bar for the page, apart from a region that scrolls on purpose.
test.beforeEach(async () => resetRateLimits());

const PAGES: [string, string][] = [
  ["/app", "Overview"],
  ["/app/onboarding", "Your plan"],
  ["/app/today", "Today"],
  ["/app/venue", "Your venue"],
  ["/app/survey", "Survey"],
  ["/app/map", "Crowd map"],
  ["/app/people", "My people"],
  ["/app/soundcheck", "Soundcheck"],
  ["/app/sound", "Sound plan"],
  ["/app/moves", "Moves"],
  ["/app/drafts", "Drafts"],
  ["/app/ask", "Ask Nigiwai"],
  ["/app/brief", "Booking Brief"],
  ["/app/proof", "Proof"],
  ["/app/posters", "QR posters"],
];

test("reflow: every owner page fits in 320 pixels without a sideways scroll bar", async ({ page, request }, info) => {
  test.skip(info.project.name !== "phone", "one narrow profile is enough");
  test.setTimeout(300_000);
  const problems = watch(page);
  await page.setViewportSize({ width: 320, height: 640 });
  const venue = await publishedVenue(request);
  await plantCrowd(venue.businessId, venue.qrId, 90, 9);
  await plantWeek(venue.qrId, [
    [0, 19, 9], [1, 19, 9], [2, 19, 9], [3, 19, 9],
    [4, 19, 14], [5, 19, 14], [6, 19, 12],
    [0, 14, 5], [1, 14, 5],
    [3, 23, 2], [4, 23, 2],
  ]);
  await openAllWeek(venue.businessId);
  await sql("UPDATE job SET run_after = now() WHERE business_id = $1", [venue.businessId]);
  await expect
    .poll(async () => (await sql("SELECT state FROM tribe_version WHERE business_id = $1 ORDER BY version DESC LIMIT 1", [venue.businessId])).rows[0]?.state, { timeout: 120_000 })
    .toMatch(/provisional|named/);
  await plantPool(venue.tenantId, venue.businessId, ["Amber Lanes", "Birch and Wire", "Cold Harbour", "Dune Parade", "Ember Choir", "Fallow Fields", "Garnet Row"]);
  await sql("INSERT INTO move (tenant_id, business_id, kind, title, started_on, source, weekdays, hour_from, hour_to) VALUES ($1, $2, 'act', 'Residency: The Quiet Engines, every Friday evening', current_date - 14, 'manual', ARRAY[4]::smallint[], 18, 22)", [venue.tenantId, venue.businessId]);
  await signIn(page, venue.email);

  const spills: string[] = [];
  for (const [path, title] of PAGES) {
    await page.goto(path);
    await expect(page.getByRole("heading", { level: 1 }).first()).toBeVisible({ timeout: 30_000 });
    await page.waitForLoadState("networkidle").catch(() => undefined);
    const wide = await page.evaluate(() => {
      const width = document.documentElement.clientWidth;
      const scrolls = (el: Element): boolean => {
        for (let n: Element | null = el; n && n !== document.body; n = n.parentElement) {
          const o = getComputedStyle(n).overflowX;
          if ((o === "auto" || o === "scroll" || o === "hidden") && n !== document.documentElement) return true;
        }
        return false;
      };
      const out: string[] = [];
      for (const el of Array.from(document.querySelectorAll("body *"))) {
        const r = el.getBoundingClientRect();
        if (r.width === 0 || r.height === 0) continue;
        if (r.right > width + 1 && !scrolls(el)) {
          out.push(`${el.tagName.toLowerCase()}${el.className && typeof el.className === "string" ? "." + el.className.split(" ").join(".") : ""} right=${Math.round(r.right)}`);
          if (out.length >= 4) break;
        }
      }
      return { scrollWidth: document.documentElement.scrollWidth, width, out };
    });
    if (wide.scrollWidth > wide.width + 1 || wide.out.length) spills.push(`${title} (${path}): page ${wide.scrollWidth}px in ${wide.width}px; ${wide.out.join("; ")}`);
    await shot(page, info, `reflow-${path.replace(/\W+/g, "-").replace(/^-|-$/g, "") || "home"}`);
  }
  expect(spills).toEqual([]);
  expect(problems.filter((p) => !/_rsc=|ERR_ABORTED|tile|openfreemap|Failed to load resource/.test(p))).toEqual([]);
});
