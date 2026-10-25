import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page } from "@playwright/test";
import { plantCrowd, plantGrow, publishedVenue, resetRateLimits, setTheme, shot, signIn, sql, watch } from "./helpers";

test.beforeEach(async () => resetRateLimits());

const tolerated = /openfreemap|ERR_FAILED|Failed to load resource|webgl|GPU/i; // map tiles come from a third party
const prefetch = /requestfailed: GET \S+[?&]_rsc=\S+ net::ERR_ABORTED/;

async function a11y(page: Page, label: string) {
  const result = await new AxeBuilder({ page }).exclude(".maplibregl-canvas").analyze();
  expect(result.violations.map((v) => `${label}: ${v.id} ${v.nodes.map((n) => n.html.slice(0, 120)).join(" | ")}`)).toEqual([]);
}

async function fitted(businessId: string): Promise<void> {
  await sql("UPDATE job SET run_after = now() WHERE business_id = $1", [businessId]);
  await expect
    .poll(async () => (await sql("SELECT state FROM tribe_version WHERE business_id = $1 ORDER BY version DESC LIMIT 1", [businessId])).rows[0]?.state, { timeout: 120_000 })
    .toMatch(/provisional|named/);
}

test("crowd map: a group Grow found no place for is a dashed candidate gap, and logged changes are flags on the timeline", async ({ page, request }, info) => {
  test.setTimeout(300_000);
  const problems = watch(page);
  const venue = await publishedVenue(request);
  await plantCrowd(venue.businessId, venue.qrId, 90, 7);
  await fitted(venue.businessId);
  await plantGrow(venue.tenantId, venue.businessId, "apart");
  // a change the owner logged, on the last day the planted crowd scanned
  const day = (await sql<{ d: string }>("SELECT to_char(max(local_date), 'YYYY-MM-DD') AS d FROM response WHERE qr_point_id = $1", [venue.qrId])).rows[0]!.d;
  await signIn(page, venue.email);
  const me = await (await page.request.get("/api/v1/auth/me")).json();
  const made = await page.request.post(`/api/v1/tenants/${venue.tenantId}/businesses/${venue.businessId}/moves`, {
    headers: { "x-csrf-token": me.csrf_token },
    data: { kind: "act", title: "Booked The Quiet Engines", started_on: day },
  });
  expect(made.status()).toBe(201);

  await page.goto("/app/map");
  await expect(page.getByRole("heading", { name: "Crowd map", level: 1 })).toBeVisible();
  const box = page.locator(".crowdmap");
  await expect(box).toHaveAttribute("data-ready", "1", { timeout: 30_000 });
  // the layer buttons exist and are on by default
  const gapsOn = page.getByRole("button", { name: "Gaps", pressed: true });
  const movesOn = page.getByRole("button", { name: "Moves", pressed: true });
  await expect(gapsOn).toBeVisible();
  await expect(movesOn).toBeVisible();
  await expect(box).toHaveAttribute("data-gaps", "1"); // one group has no place of its own

  // the flag on the timeline for the change, and what it says when opened
  const flag = page.getByTestId("move-flag");
  await expect(flag).toHaveCount(1);
  await flag.click();
  await expect(page.getByTestId("move-title")).toHaveText("Booked The Quiet Engines");
  await expect(page.getByTestId("inspector")).toContainText("never says the change caused anything");
  await shot(page, info, "map-move-flag");
  await a11y(page, "map with a move flag");

  // the list view carries both as text for anyone not using the map
  await page.getByRole("button", { name: "List", exact: true }).click();
  const list = page.getByTestId("list-view");
  await expect(list).toContainText("Candidate gap");
  await expect(list).toContainText("Booked The Quiet Engines");
  await list.getByRole("row", { name: /Candidate gap/ }).getByRole("button").click();
  await expect(page.getByTestId("gap-title")).toContainText("no place of");
  await expect(page.getByTestId("inspector")).toContainText("a candidate, not a finding");
  await expect(page.getByTestId("inspector")).toContainText("Source: Grow");
  await shot(page, info, "map-gap");
  await a11y(page, "map gap inspector");
  await setTheme(page, "dark");
  await shot(page, info, "map-gap", "dark");
  await a11y(page, "map gap inspector dark");
  await setTheme(page, "light");

  // turning the layers off takes them off the map and off the timeline
  await page.getByRole("button", { name: "Map", exact: true }).click();
  await page.getByRole("button", { name: "Gaps" }).click();
  await page.getByRole("button", { name: "Moves" }).click();
  await expect(box).toHaveAttribute("data-gaps", "0");
  await expect(page.getByTestId("move-flag")).toHaveCount(0);

  // the saved view keeps the layers
  await expect(page).toHaveURL(/layers=/);
  expect(decodeURIComponent(new URL(page.url()).searchParams.get("layers") ?? "")).not.toMatch(/gaps|moves/);
  expect(problems.filter((p) => !tolerated.test(p) && !prefetch.test(p))).toEqual([]);
});

test("crowd map: with no Grow run and no logged change, there is no gap and no flag, and nothing is claimed", async ({ page, request }) => {
  test.setTimeout(240_000);
  const problems = watch(page);
  const venue = await publishedVenue(request);
  await plantCrowd(venue.businessId, venue.qrId, 90, 9);
  await fitted(venue.businessId);
  await signIn(page, venue.email);
  await page.goto("/app/map");
  const box = page.locator(".crowdmap");
  await expect(box).toHaveAttribute("data-ready", "1", { timeout: 30_000 });
  await expect(box).toHaveAttribute("data-gaps", "0");
  await expect(page.getByTestId("move-flag")).toHaveCount(0);
  expect(problems.filter((p) => !tolerated.test(p) && !prefetch.test(p))).toEqual([]);
});

test("crowd map: a Grow run made for older groups draws no gap", async ({ page, request }) => {
  test.setTimeout(300_000);
  const problems = watch(page);
  const venue = await publishedVenue(request);
  await plantCrowd(venue.businessId, venue.qrId, 90, 11);
  await fitted(venue.businessId);
  await plantGrow(venue.tenantId, venue.businessId, "apart");
  // the groups move on: a newer version exists, so the run no longer belongs to them
  await sql(
    "INSERT INTO tribe_version (tenant_id, business_id, version, state, n, input_hash, result) SELECT tenant_id, business_id, version + 1, state, n, input_hash || 'x', result FROM tribe_version WHERE business_id = $1 ORDER BY version DESC LIMIT 1",
    [venue.businessId],
  );
  await signIn(page, venue.email);
  await page.goto("/app/map");
  const box = page.locator(".crowdmap");
  await expect(box).toHaveAttribute("data-ready", "1", { timeout: 30_000 });
  await expect(box).toHaveAttribute("data-gaps", "0");
  expect(problems.filter((p) => !tolerated.test(p) && !prefetch.test(p))).toEqual([]);
});
