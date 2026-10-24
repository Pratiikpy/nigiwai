import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page } from "@playwright/test";
import { resetRateLimits, setTheme, shot, sql, watch } from "./helpers";

// Judge mode runs against the real demo venues, built from public lineups and Qloo: `uv run python -m nigiwai_api.demo`
// (needs a Qloo key and the network). The assertions are about structure and honesty, not about which acts Qloo returns.
type Venue = { slug: string; name: string; city: string; summary: { top?: string[]; wildcard?: string | null; events?: number } };

test.beforeEach(async () => resetRateLimits());

async function a11y(page: Page, label: string) {
  const result = await new AxeBuilder({ page }).exclude(".maplibregl-canvas").analyze();
  expect(result.violations.map((v) => `${label}: ${v.id} ${v.nodes.map((n) => n.html.slice(0, 120)).join(" | ")}`)).toEqual([]);
}

async function built(page: Page): Promise<Venue[]> {
  const res = await page.request.get("/api/v1/public/demo");
  expect(res.ok()).toBe(true);
  const venues = (await res.json()) as Venue[];
  expect(venues.length, "no demo venue is built: run `uv run python -m nigiwai_api.demo`").toBeGreaterThan(0);
  return venues;
}

const tolerated = /openfreemap|ERR_FAILED|Failed to load resource|webgl|GPU/i; // map tiles come from a third party
// The browser cancels the link prefetches still in flight when a click navigates away; that is not a failed request.
const prefetch = /requestfailed: GET \S+\?_rsc=\S+ net::ERR_ABORTED/;

test("landing: the front door says what it is, lists the real venues and needs no account", async ({ page }, info) => {
  const problems = watch(page);
  const venues = await built(page);
  await page.goto("/");
  await expect(page.getByRole("heading", { name: /Soundcheck any act on your crowd before you book it/, level: 1 })).toBeVisible();
  await expect(page.getByTestId("venue-card")).toHaveCount(venues.length);
  for (const v of venues) await expect(page.getByTestId("venue-card").filter({ hasText: v.name })).toBeVisible();
  // every card says where its crowd comes from, in the product's own label
  await expect(page.getByTestId("venue-card").first()).toContainText("public lineups");
  await expect(page.getByRole("link", { name: "Create an account" }).first()).toBeVisible();
  await expect(page.getByText("Where an AI service is connected")).toBeVisible();
  await shot(page, info, "landing");
  await a11y(page, "landing");
  await setTheme(page, "dark");
  await shot(page, info, "landing", "dark");
  await a11y(page, "landing dark");
  expect(problems.filter((p) => !prefetch.test(p))).toEqual([]);

  await page.getByRole("link", { name: "Try a venue" }).click();
  await expect(page).toHaveURL(/\/try$/);
  await expect(page.getByRole("heading", { name: "Try a venue. No sign-up.", level: 1 })).toBeVisible();
  await expect(page.getByTestId("venue-card")).toHaveCount(venues.length);
  await expect(page.getByText("each network can run a few every ten minutes")).toBeVisible();
  await shot(page, info, "try");
  await a11y(page, "try");
  expect(problems.filter((p) => !prefetch.test(p))).toEqual([]);
});

test("a demo venue: suggested acts, a full verdict with its working, the comparison, and the Qloo calls", async ({ page }, info) => {
  test.setTimeout(120_000);
  const problems = watch(page);
  const [venue] = await built(page);
  if (!venue) throw new Error("unreachable");
  await page.goto("/try");
  // PRD phase 3b: judge mode opens a real venue in under 10 seconds from the stored results, with the first suggested acts on screen
  const openedAt = Date.now();
  await page.getByTestId("venue-card").filter({ hasText: venue.name }).click();
  await expect(page).toHaveURL(new RegExp(`/try/${venue.slug}$`));
  await expect(page.getByRole("heading", { name: venue.name, level: 1 })).toBeVisible();
  await expect(page.getByRole("group", { name: "Suggested acts" }).getByRole("button").first()).toBeVisible();
  const openedIn = Date.now() - openedAt;
  info.annotations.push({ type: "judge mode open time", description: `${venue.name} opened with suggestions in ${openedIn} ms` });
  expect(openedIn).toBeLessThan(10_000);
  await expect(page.getByText("Modelled from public lineups.")).toBeVisible();
  // nothing that needs an account is offered
  await expect(page.getByRole("link", { name: "Open My people" })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Suggest again" })).toHaveCount(0);

  const chips = page.getByRole("group", { name: "Suggested acts" }).getByRole("button");
  await expect(chips.first()).toBeVisible();
  expect(await chips.count()).toBeGreaterThanOrEqual(3);
  const first = (await chips.first().innerText()).split("\n")[0] ?? "";
  await chips.first().click();

  const verdict = page.getByTestId("verdict");
  await expect(verdict).toBeVisible();
  await expect(verdict).toHaveAttribute("data-status", "ok");
  await expect(verdict).toContainText(first);
  const score = Number(await page.getByTestId("score").first().innerText());
  expect(score).toBeGreaterThan(0);
  expect(score).toBeLessThanOrEqual(100);
  await expect(page.getByTestId("range").first()).toBeVisible(); // the score always comes with its range
  // the deep link carries the verdict, and a stranger can open it
  await expect(page).toHaveURL(/\?sc=[0-9a-f-]{36}$/);
  // no feedback box and no share affordance for a visitor
  await expect(page.getByTestId("feedback")).toHaveCount(0);

  // Qloo and an AI alone: with no AI service connected it says so rather than inventing a list
  const compare = page.getByTestId("compare");
  await expect(compare).toBeVisible();
  await expect(page.getByTestId("compare-summary")).not.toBeEmpty();

  await page.getByText("The Qloo calls behind this score").click();
  await expect(page.getByTestId("calls")).toBeVisible();
  expect(await page.getByTestId("calls").locator("li").count()).toBeGreaterThanOrEqual(1);
  await shot(page, info, "demo-soundcheck");
  await a11y(page, "demo soundcheck");
  await setTheme(page, "dark");
  await shot(page, info, "demo-soundcheck", "dark");
  await a11y(page, "demo soundcheck dark");
  expect(problems.filter((p) => !prefetch.test(p))).toEqual([]);

  // a deep link opens in a clean browser context with no history
  const url = page.url();
  const fresh = await page.context().browser()!.newContext();
  const other = await fresh.newPage();
  await other.goto(url);
  await expect(other.getByTestId("verdict")).toContainText(first);
  await fresh.close();
});

test("a demo venue: any act can be checked, a made-up name finds nothing, and nothing is stored under a person", async ({ page }, info) => {
  test.setTimeout(150_000);
  const problems = watch(page);
  const sessions = async () => (await sql("SELECT count(*)::int AS n FROM app_session")).rows[0]?.n;
  const sessionsBefore = await sessions(); // other tests sign owners in, so compare before and after rather than to zero
  const [venue] = await built(page);
  if (!venue) throw new Error("unreachable");
  await page.goto(`/try/${venue.slug}`);
  const box = page.getByLabel("Search for an act");
  await expect(box).toBeVisible();
  // a string that is no name: Qloo's search is fuzzy, so either an honest empty answer or its nearest matches, never an error
  await box.fill("Qzxjvwmplkq");
  await expect(page.getByText(/No artist by that name/).or(page.getByRole("list", { name: "Matching acts" }))).toBeVisible({ timeout: 30_000 });
  await expect(page.locator('.banner[data-tone="error"]')).toHaveCount(0); // Next's own route announcer is also an alert
  // a well-known act: found, and checked
  await box.fill("Radiohead");
  const row = page.getByRole("listitem").filter({ hasText: "Radiohead" }).first();
  await expect(row).toBeVisible({ timeout: 30_000 });
  await row.getByRole("button", { name: "Soundcheck" }).click();
  await expect(page.getByTestId("verdict")).toBeVisible({ timeout: 60_000 });
  await expect(page.getByTestId("verdict")).toContainText("Radiohead");
  await shot(page, info, "demo-any-act");
  await a11y(page, "demo any act");
  expect(problems.filter((p) => !/429/.test(p) && !prefetch.test(p))).toEqual([]);
  // no account and no cookie were created for the visitor
  expect(await page.context().cookies()).toEqual([]);
  expect(await sessions()).toBe(sessionsBefore);
});

test("a demo venue: the crowd map and the booking brief open for a visitor, and the brief downloads as a PDF", async ({ page }, info) => {
  test.setTimeout(120_000);
  const problems = watch(page);
  const [venue] = await built(page);
  if (!venue) throw new Error("unreachable");
  await page.goto(`/try/${venue.slug}`);

  await page.getByRole("tab", { name: "Crowd map" }).click();
  await expect(page).toHaveURL(/tab=map/);
  await expect(page.getByRole("heading", { name: "Crowd map", level: 2 })).toBeVisible();
  await expect(page.getByTestId("inspector")).toBeVisible();
  await expect(page.getByText("This venue is shown from public lineups, so there are no guest scans yet.")).toBeVisible();
  await page.getByRole("button", { name: "List", exact: true }).click();
  await expect(page.getByTestId("list-view")).toBeVisible();
  await shot(page, info, "demo-map");
  await a11y(page, "demo map");
  expect(problems.filter((p) => !tolerated.test(p) && !prefetch.test(p))).toEqual([]);

  await page.getByRole("tab", { name: "Booking Brief" }).click();
  await expect(page).toHaveURL(/tab=brief/);
  await expect(page.getByTestId("brief")).toHaveAttribute("data-status", "ok");
  await expect(page.getByRole("heading", { name: "Three acts to consider" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Create a share link" })).toHaveCount(0);
  const href = await page.getByTestId("pdf").getAttribute("href");
  const pdf = await page.request.get(href as string);
  expect(pdf.status()).toBe(200);
  expect(pdf.headers()["content-type"]).toBe("application/pdf");
  expect((await pdf.body()).subarray(0, 5).toString()).toBe("%PDF-");
  await shot(page, info, "demo-brief");
  await a11y(page, "demo brief");
  expect(problems.filter((p) => !tolerated.test(p) && !prefetch.test(p))).toEqual([]);

  // switching views keeps the venue, and the tabs work from the keyboard
  await page.getByRole("tab", { name: "Booking Brief" }).focus();
  await page.keyboard.press("ArrowLeft");
  await expect(page.getByRole("tab", { name: "Crowd map" })).toHaveAttribute("aria-selected", "true");
  await page.keyboard.press("Home");
  await expect(page.getByRole("tab", { name: "Soundcheck" })).toHaveAttribute("aria-selected", "true");
  await expect(page).not.toHaveURL(/tab=/);
});

test("a demo venue: an unknown name, a malformed name and an unready venue each get a plain page", async ({ page }, info) => {
  const problems = watch(page);
  for (const slug of ["no-such-venue", "Bad_Slug"]) {
    await page.goto(`/try/${slug}`);
    await expect(page.getByRole("heading", { name: "We have no demo venue by that name.", level: 1 })).toBeVisible();
    await expect(page.getByRole("link", { name: "See the demo venues" })).toBeVisible();
  }
  await shot(page, info, "demo-missing");
  await a11y(page, "demo missing");

  // a venue that is still being built is not listed and says so plainly instead of showing half a page
  const made = await sql<{ id: string }>(
    "INSERT INTO business (tenant_id, name, type) VALUES ('6e1c0de0-0000-4000-8000-00000000d3a0', 'Unready room', 'bar') RETURNING id",
  );
  const businessId = made.rows[0]?.id;
  try {
    await sql("INSERT INTO demo_venue (slug, name, city, blurb, business_id, status) VALUES ('e2e-unready', 'Unready room', 'Nowhere', 'Not built.', $1, 'building')", [businessId]);
    expect(((await (await page.request.get("/api/v1/public/demo")).json()) as Venue[]).map((v) => v.slug)).not.toContain("e2e-unready");
    await page.goto("/try/e2e-unready");
    await expect(page.getByRole("heading", { name: "This demo venue is not available right now.", level: 1 })).toBeVisible();
    await a11y(page, "demo unready");
  } finally {
    await sql("DELETE FROM business WHERE id = $1", [businessId]); // removes its demo row too
  }
  // the failing API responses are the point of this test; nothing else may be reported
  expect(problems.filter((p) => !/404|422|503|Failed to load resource/.test(p) && !prefetch.test(p))).toEqual([]);
});
