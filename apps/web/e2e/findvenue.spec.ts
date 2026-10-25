import { randomUUID } from "node:crypto";
import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page } from "@playwright/test";
import { resetRateLimits, setTheme, shot, sql, watch } from "./helpers";

// Try any venue (PRD M24, M25). Looking a venue up and asking for it need MusicBrainz, so those two calls are answered here; everything
// after them is the real API reading real rows: the page for a venue that is building, failed or ready, and the polling between them.
// The real MusicBrainz and Qloo build runs end to end in live.spec.ts.
const DEMO_TENANT = "6e1c0de0-0000-4000-8000-00000000d3a0";
const MBID = "d7cb3789-c62f-4f5c-a0e0-9e1ceb525114";

test.beforeEach(async () => resetRateLimits());

async function a11y(page: Page, label: string) {
  const result = await new AxeBuilder({ page }).exclude(".maplibregl-canvas").analyze();
  expect(result.violations.map((v) => `${label}: ${v.id} ${v.nodes.map((n) => n.html.slice(0, 120)).join(" | ")}`)).toEqual([]);
}

const prefetch = /requestfailed: GET \S+[?&]_rsc=\S+ net::ERR_ABORTED/;
// A venue that is still building (or failed) answers 503 on purpose, and the page then asks its status route what that means.
const building503 = /status of 503 \(Service Unavailable\) @ \S+\/api\/v1\/public\/demo\/req-e2e-/;
// An unknown venue answers 404 on purpose.
const unknown404 = /status of 404 \(Not Found\) @ \S+\/api\/v1\/public\/demo\/(req-e2e-|no-such-venue)/;

type Planted = { slug: string; businessId: string };
const planted: string[] = [];

test.afterEach(async () => {
  for (const id of planted.splice(0)) await sql("DELETE FROM business WHERE id = $1", [id]);
});

async function plant(opts: { name: string; status: "building" | "ready" | "failed"; error?: string; askedHoursAgo?: number; mbid?: string }): Promise<Planted> {
  const tag = randomUUID().replace(/-/g, "").slice(0, 8);
  const slug = `req-e2e-${tag}`;
  const businessId = randomUUID();
  await sql("INSERT INTO business (id, tenant_id, name, type) VALUES ($1, $2, $3, 'live_music_venue')", [businessId, DEMO_TENANT, opts.name]);
  await sql(
    `INSERT INTO demo_venue (slug, name, city, blurb, business_id, status, error, summary, refreshed_at, requested, place_mbid, requested_at)
     VALUES ($1, $2, 'Chicago', $3, $4, $5, $6, $7::jsonb, CASE WHEN $5 = 'ready' THEN now() END, true, $8, now() - make_interval(hours => $9::int))`,
    [
      slug,
      opts.name,
      "A venue a visitor asked for in Chicago, read from the public lineups of its past events.",
      businessId,
      opts.status,
      opts.error ?? null,
      JSON.stringify(opts.status === "ready" ? { events: 24, acts_matched: 31, performers: 58, first: "2015-03-01", last: "2026-09-12" } : {}),
      opts.mbid ?? randomUUID(),
      opts.askedHoursAgo ?? 0,
    ],
  );
  planted.push(businessId);
  return { slug, businessId };
}

const place = (over: Record<string, unknown>) => ({
  mbid: randomUUID(),
  name: "Test Room",
  area: "Chicago",
  address: "1 Example St., Chicago, IL",
  kind: "Venue",
  mappable: true,
  slug: null,
  status: null,
  ...over,
});

test("try any venue: search, a venue with no position cannot be built, asking opens its page, and the page waits for the build", async ({ page }, info) => {
  test.setTimeout(120_000);
  const problems = watch(page);
  const mine = await plant({ name: "Test Room", status: "building", mbid: MBID });
  const ready = await plant({ name: "Test Room North", status: "ready" });
  let asked: unknown = null;
  await page.route("**/api/v1/public/demo/find**", (route) =>
    route.fulfill({
      json: {
        places: [
          place({ mbid: MBID, name: "Test Room" }),
          place({ name: "Test Room Annex", mappable: false }),
          place({ name: "Test Room North", slug: ready.slug, status: "ready" }),
        ],
      },
    }),
  );
  await page.route("**/api/v1/public/demo/request", async (route) => {
    asked = route.request().postDataJSON();
    await route.fulfill({ json: { slug: mine.slug, status: "building" } });
  });

  await page.goto("/try");
  const card = page.getByTestId("find-venue");
  await expect(card).toBeVisible();
  await expect(card).toContainText("It takes a few minutes. The venue is kept for seven days, then deleted.");
  await expect(card).toContainText("at least 10 past events with lineups on MusicBrainz and at least 15 of its acts that Qloo knows");
  // too short a name is not sent
  const search = card.getByRole("button", { name: "Search", exact: true });
  await card.getByLabel("Venue name").fill("ab");
  await expect(search).toBeDisabled();
  await card.getByLabel("Venue name").fill("Test Room");
  await expect(search).toBeEnabled();
  await shot(page, info, "find-venue");
  await search.click();

  const found = page.getByTestId("found-place");
  await expect(found).toHaveCount(3);
  // a venue that can be built offers to build it; one with no position says why it cannot; one already built opens
  await expect(found.nth(0).getByRole("button", { name: "Build this venue" })).toBeVisible();
  await expect(found.nth(1)).toContainText("no position for this venue");
  await expect(found.nth(1).getByRole("button")).toHaveCount(0);
  await expect(found.nth(2)).toContainText("Already built.");
  await expect(found.nth(2).getByRole("link", { name: "Open" })).toHaveAttribute("href", `/try/${ready.slug}`);
  await shot(page, info, "find-venue-results");
  await a11y(page, "try with results");
  await setTheme(page, "dark");
  await shot(page, info, "find-venue-results", "dark");
  await a11y(page, "try with results dark");
  await setTheme(page, "light");

  // asking sends the MusicBrainz id and nothing else, and leads to the venue's own page
  await found.nth(0).getByRole("button", { name: "Build this venue" }).click();
  await expect(page).toHaveURL(new RegExp(`/try/${mine.slug}$`));
  expect(asked).toEqual({ mbid: MBID });
  const wait = page.getByTestId("venue-building");
  await expect(wait).toBeVisible();
  await expect(page.getByRole("heading", { name: "Test Room", level: 1 })).toBeVisible();
  await expect(wait).toContainText("the venue is kept for seven days");
  await expect(wait.getByRole("status")).toContainText("Still building");
  await expect(page.getByText("Each act is looked up in Qloo by exact name")).toBeVisible();
  await shot(page, info, "venue-building");
  await a11y(page, "venue building");
  await setTheme(page, "dark");
  await shot(page, info, "venue-building", "dark");
  await a11y(page, "venue building dark");
  await setTheme(page, "light");

  // the build finishes while the page is open: it opens by itself, and says it was asked for and when it goes
  await sql(
    "UPDATE demo_venue SET status = 'ready', error = NULL, refreshed_at = now(), summary = $2::jsonb WHERE slug = $1",
    [mine.slug, JSON.stringify({ events: 24, acts_matched: 31, performers: 58, first: "2015-03-01", last: "2026-09-12" })],
  );
  await expect(page.getByTestId("venue-building")).toHaveCount(0, { timeout: 15_000 });
  await expect(page.getByRole("heading", { name: "Test Room", level: 1 })).toBeVisible();
  await expect(page.getByText("Venue you asked for · Chicago")).toBeVisible();
  await expect(page.getByText("24 events")).toBeVisible();
  await expect(page.getByText("It is kept until")).toBeVisible();
  await expect(page.getByText("then deleted. Anyone with this address can open it until then.")).toBeVisible();
  await expect(page.getByText("Built", { exact: false }).first()).toBeVisible();
  await shot(page, info, "venue-requested-ready");
  await a11y(page, "requested venue");
  await setTheme(page, "dark");
  await shot(page, info, "venue-requested-ready", "dark");
  await a11y(page, "requested venue dark");
  expect(problems.filter((p) => !prefetch.test(p) && !building503.test(p))).toEqual([]);
});

test("try any venue: a build that failed says why in plain words, and can be asked for again after an hour", async ({ page }, info) => {
  test.setTimeout(90_000);
  const problems = watch(page);
  const thin = await plant({
    name: "Thin Room",
    status: "failed",
    error: "DemoError: Not enough public data yet: only 4 events with lineups, and at least 10 are needed.",
    mbid: MBID,
  });
  await page.goto(`/try/${thin.slug}`);
  const failed = page.getByTestId("venue-failed");
  await expect(failed).toBeVisible();
  await expect(page.getByRole("heading", { name: "We couldn’t build Thin Room.", level: 1 })).toBeVisible();
  await expect(failed).toContainText("Not enough public data yet: only 4 events with lineups");
  // the product's own words, never a class name
  await expect(failed).not.toContainText("DemoError");
  // asked a moment ago, so asking again waits
  await expect(failed.getByRole("button", { name: "Ask again" })).toBeDisabled();
  await expect(failed).toContainText("You can ask again after");
  await expect(failed.getByRole("link", { name: "Try another venue" })).toHaveAttribute("href", "/try");
  await shot(page, info, "venue-failed");
  await a11y(page, "venue failed");
  await setTheme(page, "dark");
  await shot(page, info, "venue-failed", "dark");
  await a11y(page, "venue failed dark");
  await setTheme(page, "light");

  // an hour later it may be asked for again, which starts a build and shows the wait
  await sql("UPDATE demo_venue SET requested_at = now() - interval '2 hours' WHERE slug = $1", [thin.slug]);
  let asked: unknown = null;
  await page.route("**/api/v1/public/demo/request", async (route) => {
    asked = route.request().postDataJSON();
    await sql("UPDATE demo_venue SET status = 'building', error = NULL, requested_at = now() WHERE slug = $1", [thin.slug]);
    await route.fulfill({ json: { slug: thin.slug, status: "building" } });
  });
  await page.reload();
  const again = page.getByTestId("venue-failed").getByRole("button", { name: "Ask again" });
  await expect(again).toBeEnabled();
  await expect(page.getByTestId("venue-failed")).not.toContainText("You can ask again after");
  await again.click();
  expect(asked).toEqual({ mbid: MBID });
  await expect(page.getByTestId("venue-building")).toBeVisible();
  await expect(page.getByRole("heading", { name: "Thin Room", level: 1 })).toBeVisible();
  await shot(page, info, "venue-asked-again");

  // a fault that is not the product's own words is told as a plain apology, with no internals
  await sql("UPDATE demo_venue SET status = 'failed', error = $2, requested_at = now() - interval '2 hours' WHERE slug = $1", [
    thin.slug,
    "LineupError: MusicBrainz answered 500",
  ]);
  await page.unroute("**/api/v1/public/demo/request");
  await page.reload();
  const fault = page.getByTestId("venue-failed");
  await expect(fault).toContainText("Something went wrong while building this venue. Please try again in a little while.");
  await expect(fault).not.toContainText("LineupError");
  await expect(fault).not.toContainText("500");
  expect(problems.filter((p) => !prefetch.test(p) && !building503.test(p))).toEqual([]);
});

test("try any venue: a deleted venue says it is gone, an unknown prepared name is unchanged, and a requested venue is kept out of search engines", async ({ page }, info) => {
  const problems = watch(page);
  await page.goto("/try/req-e2e-nothing-here-0000");
  await expect(page.getByRole("heading", { name: "This venue is gone.", level: 1 })).toBeVisible();
  await expect(page.getByText("A venue someone asks for is kept for seven days, then deleted.")).toBeVisible();
  await expect(page.getByRole("link", { name: "See the demo venues" })).toBeVisible();
  await shot(page, info, "venue-gone");
  await a11y(page, "venue gone");

  await page.goto("/try/no-such-venue");
  await expect(page.getByRole("heading", { name: "We have no demo venue by that name.", level: 1 })).toBeVisible();

  const requested = await page.request.get("/try/req-e2e-nothing-here-0000");
  expect(await requested.text()).toMatch(/<meta name="robots" content="noindex, nofollow"/);
  const prepared = await page.request.get("/try/mercury-lounge");
  expect(await prepared.text()).not.toMatch(/noindex/);
  // 404s are the page's own answer here, not failures
  expect(problems.filter((p) => !prefetch.test(p) && !unknown404.test(p))).toEqual([]);
});

test("try any venue: an empty search, a busy site and a service that is down each say so", async ({ page }, info) => {
  const problems = watch(page);
  let mode: "empty" | "busy" | "down" = "empty";
  await page.route("**/api/v1/public/demo/find**", (route) => {
    if (mode === "empty") return route.fulfill({ json: { places: [] } });
    if (mode === "busy") return route.fulfill({ status: 429, json: { detail: "The demo is busy. Please try again in a little while." } });
    return route.fulfill({ status: 503, json: { detail: "Venue search is not answering right now. Please try again." } });
  });
  await page.goto("/try");
  const card = page.getByTestId("find-venue");
  await card.getByLabel("Venue name").fill("Nowhere Hall");
  await card.getByLabel("Venue name").press("Enter"); // the form submits from the keyboard
  await expect(page.getByTestId("no-places")).toContainText("MusicBrainz has no venue called “Nowhere Hall”.");
  await shot(page, info, "find-venue-empty");
  await a11y(page, "try empty search");

  mode = "busy";
  await card.getByRole("button", { name: "Search", exact: true }).click();
  await expect(card.getByRole("alert")).toContainText("The demo is busy.");
  await expect(page.getByTestId("no-places")).toHaveCount(0); // an old result is not left standing under a new error

  mode = "down";
  await card.getByRole("button", { name: "Search", exact: true }).click();
  await expect(card.getByRole("alert")).toContainText("Venue search is not answering right now.");
  await a11y(page, "try search error");
  // 429 and 503 are the scripted answers here, so the browser logs them as failed loads
  expect(problems.filter((p) => !prefetch.test(p) && !/status of (429|503) .* @ \S+\/api\/v1\/public\/demo\/find/.test(p))).toEqual([]);
});

test("try any venue: every state fits in 320 pixels without a sideways scroll bar", async ({ page }, info) => {
  test.skip(info.project.name !== "phone", "one narrow profile is enough");
  test.setTimeout(90_000);
  await page.setViewportSize({ width: 320, height: 640 });
  const long = "A Very Long Venue Name That Goes On And On, Chicago, Illinois, United States";
  const building = await plant({ name: long, status: "building" });
  const failed = await plant({ name: long, status: "failed", error: "DemoError: Not enough public data yet: only 4 events with lineups, and at least 10 are needed.", askedHoursAgo: 0 });
  const ready = await plant({ name: long, status: "ready" });
  await page.route("**/api/v1/public/demo/find**", (route) =>
    route.fulfill({
      json: {
        places: [
          place({ name: long, address: "1234 Extraordinarily Long Street Name Boulevard, Chicago, Illinois 60601, United States of America" }),
          place({ name: "No position", mappable: false }),
          place({ name: long, slug: ready.slug, status: "ready" }),
        ],
      },
    }),
  );
  const spills: string[] = [];
  const fits = async (label: string) => {
    await page.waitForLoadState("networkidle").catch(() => undefined);
    const wide = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
    if (wide > 1) spills.push(`${label}: ${wide}px too wide`);
  };
  await page.goto("/try");
  await page.getByTestId("find-venue").getByLabel("Venue name").fill("Long");
  await page.getByTestId("find-venue").getByRole("button", { name: "Search", exact: true }).click();
  await expect(page.getByTestId("found-place")).toHaveCount(3);
  await fits("try with results");
  await page.goto(`/try/${building.slug}`);
  await expect(page.getByTestId("venue-building")).toBeVisible();
  await fits("venue building");
  await page.goto(`/try/${failed.slug}`);
  await expect(page.getByTestId("venue-failed")).toBeVisible();
  await fits("venue failed");
  await page.goto(`/try/${ready.slug}`);
  await expect(page.getByText("Venue you asked for")).toBeVisible();
  await fits("requested venue");
  await shot(page, info, "venue-requested-320");
  expect(spills).toEqual([]);
});
