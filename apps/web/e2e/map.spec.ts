import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page } from "@playwright/test";
import { randomUUID } from "node:crypto";
import http from "node:http";
import { plantCrowd, publishedVenue, resetRateLimits, setTheme, shot, signIn, sql, watch } from "./helpers";

// The API is started with NIGIWAI_NOMINATIM_URL=http://127.0.0.1:18089 (see README, "Browser tests"). This stands in for
// the public place finder, so these tests never send a question to a service we do not run; Qloo and the map tiles are real.
const STUB_PORT = 18089;
const KNOWN: Record<string, [number, number]> = { hackney: [51.545, -0.055], brixton: [51.46, -0.115] };
const asked: string[] = [];

let stub: http.Server;
test.beforeAll(async () => {
  stub = http.createServer((req, res) => {
    const url = new URL(req.url ?? "/", "http://stub");
    const q = (url.searchParams.get("q") ?? "").trim().toLowerCase();
    asked.push(q);
    res.setHeader("content-type", "application/json");
    const hit = KNOWN[q];
    res.end(JSON.stringify(hit ? [{ lat: String(hit[0]), lon: String(hit[1]), name: q, display_name: q }] : []));
  });
  await new Promise<void>((resolve) => stub.listen(STUB_PORT, "127.0.0.1", resolve));
});
test.afterAll(async () => {
  await new Promise<void>((resolve) => stub.close(() => resolve()));
});
test.beforeEach(async () => resetRateLimits());

async function openMap(page: Page) {
  await page.locator(".shell__main").waitFor(); // the shell renders once the session has loaded
  const menu = page.getByRole("button", { name: "Menu" });
  if (await menu.isVisible()) await menu.click();
  await page.getByRole("navigation", { name: "Pages" }).getByRole("link", { name: "Crowd map" }).click();
  await expect(page.getByRole("heading", { name: "Crowd map", level: 1 })).toBeVisible();
}

async function a11y(page: Page, label: string) {
  const result = await new AxeBuilder({ page }).exclude(".maplibregl-canvas").analyze();
  expect(result.violations.map((v) => `${label}: ${v.id} ${v.nodes.map((n) => n.html.slice(0, 120)).join(" | ")}`)).toEqual([]);
}

test("crowd map: a pin with no guests, then a real crowd, a second site under ten, neighbourhoods, periods, list and a saved view", async ({ page, request }, info) => {
  test.setTimeout(300_000);
  const problems = watch(page);
  const venue = await publishedVenue(request);
  await signIn(page, venue.email);
  await openMap(page);

  // No guests yet: the pin, what is around it, and a plain note about groups. No figures.
  const canvas = page.locator(".crowdmap");
  await expect(canvas).toHaveAttribute("data-ready", "1", { timeout: 30_000 });
  await expect(canvas).toHaveAttribute("data-pins", "1");
  await expect(page.getByText("Groups come from 60 guests.")).toBeVisible();
  await expect(page.getByRole("button", { name: /Main room, under 10 guests/ })).toBeVisible();
  await expect(canvas).not.toHaveAttribute("data-places", "0", { timeout: 30_000 }); // Qloo's places around the venue
  await shot(page, info, "map-empty");
  await a11y(page, "map empty");

  // A real crowd of 120 at the first site, seven at a second, and neighbourhoods named by guests.
  const me = await (await request.get("/api/v1/auth/me")).json();
  const headers = { "x-csrf-token": me.csrf_token };
  const t = `/api/v1/tenants/${venue.tenantId}`;
  const loc = await (await request.post(`${t}/businesses/${venue.businessId}/locations`, { headers, data: { name: "Garden", lat: 51.52, lon: -0.1, timezone: "Europe/London" } })).json();
  const qr2 = await (await request.post(`${t}/locations/${loc.id}/qr-points`, { headers, data: { label: "Patio" } })).json();
  await plantCrowd(venue.businessId, venue.qrId, 120, 21);
  const survey = (await sql<{ id: string; version: number }>("SELECT id, version FROM survey WHERE business_id = $1 AND status = 'published'", [venue.businessId])).rows[0]!;
  const picks = (await sql<{ entity_id: string; entity_type: string }>("SELECT DISTINCT entity_id, entity_type FROM pick LIMIT 3")).rows;
  for (let i = 0; i < 7; i++) {
    await sql("SELECT public_insert_response($1, $2, $3, 'v1', NULL, NULL, NULL, 'ok', $4, $5, $6)", [
      qr2.id,
      survey.id,
      survey.version,
      picks.map((p) => p.entity_id),
      picks.map((p) => p.entity_type),
      Buffer.from(randomUUID().replace(/-/g, ""), "hex"),
    ]);
  }
  const ids = (await sql<{ id: string }>("SELECT r.id FROM response r JOIN qr_point q ON q.id = r.qr_point_id WHERE q.id = $1 ORDER BY r.id", [venue.qrId])).rows.map((r) => r.id);
  for (const [i, id] of ids.entries()) {
    const district = i < 15 ? "Hackney" : i < 30 ? " hackney" : i < 45 ? "Brixton" : i < 51 ? "Peckham" : null;
    if (district) await sql("UPDATE response SET district = $1 WHERE id = $2", [district, id]);
  }
  await sql("UPDATE job SET run_after = now() WHERE business_id = $1", [venue.businessId]);
  await expect
    .poll(async () => (await sql("SELECT count(*)::int AS n FROM tribe_version WHERE business_id = $1 AND state IN ('provisional','named')", [venue.businessId])).rows[0]?.n, { timeout: 150_000, intervals: [3000] })
    .toBeGreaterThan(0)
    .catch(() => undefined); // groups are not what this test is about: without them the map still shows scans
  await page.reload();
  await expect(canvas).toHaveAttribute("data-ready", "1", { timeout: 30_000 });
  await expect(canvas).toHaveAttribute("data-pins", "2");
  await expect(canvas).toHaveAttribute("data-hexes", "2", { timeout: 40_000 }); // Hackney (30 guests) and Brixton (15); Peckham (6) is counted, not drawn
  await expect(page.getByRole("button", { name: "Main room, 120 scans" })).toBeVisible();
  await expect(page.getByRole("button", { name: /Garden, under 10 guests/ })).toBeVisible();
  await expect(page.getByText(/1 neighbourhood named by fewer than 10 guests is counted, not shown/)).toBeVisible();
  expect(asked.filter((q) => q === "peckham")).toHaveLength(0); // a district under ten guests is never looked up

  // Inspect the busy site: the sample size is on it, the small one says only that it is small.
  await page.getByRole("button", { name: "Main room, 120 scans" }).click();
  const inspector = page.getByTestId("inspector");
  await expect(inspector.getByRole("heading", { name: "Main room" })).toBeVisible();
  await expect(inspector.getByText("n = 120")).toBeVisible();
  await expect(inspector.getByText("Who scans here")).toBeVisible();
  await expect(inspector.getByText("Bar end")).toBeVisible();
  await shot(page, info, "map-site");
  await a11y(page, "map site");
  await page.getByRole("button", { name: /Garden, under 10 guests/ }).click();
  await expect(inspector.getByText("Under 10 guests.")).toBeVisible();
  await expect(inspector.getByText("Who scans here")).toHaveCount(0);

  // Layers, the period and the list view. Turning a layer off removes it from the map.
  await page.getByRole("button", { name: "Catchment" }).click();
  await expect(canvas).toHaveAttribute("data-hexes", "0");
  await page.getByRole("button", { name: "Catchment" }).click();
  await expect(canvas).toHaveAttribute("data-hexes", "2");
  await page.getByRole("button", { name: "7 days" }).click();
  await expect(page.getByTestId("timeline")).toContainText("scans in the last 7 days");
  await page.getByRole("button", { name: "All time" }).click();
  await page.getByRole("button", { name: "List" }).click();
  const list = page.getByTestId("list-view");
  await expect(list.getByRole("row")).not.toHaveCount(0);
  await expect(list.getByText("hackney", { exact: false }).first()).toBeVisible();
  await list.getByRole("button", { name: /hackney/i }).first().click();
  await page.getByRole("button", { name: "Map" }).click();
  await expect(page.getByTestId("inspector").getByText("Catchment").first()).toBeVisible();
  await shot(page, info, "map-catchment");
  await a11y(page, "map catchment");

  // The view is saved in the address: a reload reopens it as it was.
  expect(decodeURIComponent(page.url())).toContain("sel=cell:");
  await page.reload();
  await expect(page.getByTestId("inspector").getByText("Catchment").first()).toBeVisible();
  await setTheme(page, "dark");
  await page.waitForTimeout(1500); // the dark base map loads
  await shot(page, info, "map-catchment", "dark");
  await a11y(page, "map dark");
  expect(problems.filter((p) => !/openfreemap|webgl|GPU/i.test(p))).toEqual([]);
});

test("crowd map: with the base map blocked, the layers still work and the page says what is missing", async ({ page, request }, info) => {
  const problems = watch(page);
  await page.route("https://tiles.openfreemap.org/**", (route) => route.abort());
  const venue = await publishedVenue(request);
  await signIn(page, venue.email);
  await openMap(page);
  const canvas = page.locator(".crowdmap");
  await expect(page.getByText(/The base map couldn’t be loaded|Your browser can’t draw the map/)).toBeVisible({ timeout: 30_000 });
  // If the map could not start at all the list takes over; if only the tiles failed the pin is still there.
  const list = page.getByTestId("list-view");
  if (!(await list.isVisible())) await expect(canvas).toHaveAttribute("data-pins", "1");
  await shot(page, info, "map-no-tiles");
  await a11y(page, "map without tiles");
  expect(problems.filter((p) => !/openfreemap|ERR_FAILED|Failed to load resource|webgl|GPU/i.test(p))).toEqual([]);
});
