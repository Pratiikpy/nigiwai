import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page } from "@playwright/test";
import { plantCrowd, plantGrow, publishedVenue, resetRateLimits, setTheme, shot, signIn, sql, watch } from "./helpers";

test.beforeEach(async () => resetRateLimits());

async function a11y(page: Page, label: string) {
  const result = await new AxeBuilder({ page }).analyze();
  expect(result.violations.map((v) => `${label}: ${v.id} ${v.nodes.map((n) => n.html.slice(0, 120)).join(" | ")}`)).toEqual([]);
}
const prefetch = /requestfailed: GET \S+\?_rsc=\S+ net::ERR_ABORTED/;

async function fitted(businessId: string): Promise<void> {
  await sql("UPDATE job SET run_after = now() WHERE business_id = $1", [businessId]);
  await expect
    .poll(async () => (await sql("SELECT state FROM tribe_version WHERE business_id = $1 ORDER BY version DESC LIMIT 1", [businessId])).rows[0]?.state, { timeout: 120_000 })
    .toMatch(/provisional|named/);
}

test("grow: with no crowd it says what is missing; with groups it offers a look-up that waits, then shows the result and says when it is out of date", async ({ page, request }, info) => {
  test.setTimeout(300_000);
  const problems = watch(page);
  const venue = await publishedVenue(request);
  await signIn(page, venue.email);
  await page.goto("/app/grow");
  await expect(page.getByRole("heading", { name: "Grow", level: 1 })).toBeVisible();
  await expect(page.getByTestId("not-ready")).toHaveAttribute("data-state", "no_crowd");
  await expect(page.getByTestId("not-ready")).toContainText("Collect at least 60 guests");
  await expect(page.getByTestId("ask")).toHaveCount(0);
  await expect(page.getByTestId("notes")).toContainText("Nothing on this page is a count of customers");
  await shot(page, info, "grow-empty");
  await a11y(page, "grow empty");

  await plantCrowd(venue.businessId, venue.qrId, 90, 5);
  await fitted(venue.businessId);
  await page.reload();
  await expect(page.getByTestId("not-ready")).toHaveAttribute("data-state", "not_run");
  await expect(page.getByTestId("not-ready")).toContainText("Nothing has been looked up yet");
  await expect(page.getByTestId("ask")).toBeVisible();
  await expect(page.getByTestId("not-ready")).toContainText("Opening this page never calls Qloo");
  await shot(page, info, "grow-not-run");
  await a11y(page, "grow not run");

  // The look-up is sent to the server (the request is held back here so no Qloo call is made for invented picks), then the page
  // shows the waiting state and updates itself when the stored row changes.
  let asked = 0;
  await page.route("**/businesses/*/grow", async (route) => {
    if (route.request().method() === "POST") {
      asked += 1;
      await route.fulfill({ status: 202, contentType: "application/json", body: JSON.stringify({ queued: true }) });
    } else {
      await route.continue();
    }
  });
  await sql("INSERT INTO grow_run (business_id, tenant_id, status) VALUES ($1, $2, 'queued') ON CONFLICT (business_id) DO UPDATE SET status = 'queued'", [venue.businessId, venue.tenantId]);
  await page.getByTestId("ask").click();
  await expect.poll(() => asked).toBe(1);
  await expect(page.getByTestId("not-ready")).toHaveAttribute("data-state", "queued");
  await expect(page.getByTestId("not-ready")).toContainText("Looking things up");
  await expect(page.getByTestId("ask")).toHaveCount(0);
  await shot(page, info, "grow-waiting");
  await a11y(page, "grow waiting");

  await plantGrow(venue.tenantId, venue.businessId, "crowd");
  await expect(page.getByTestId("ghosts")).toBeVisible({ timeout: 15_000 });
  await expect(page.getByTestId("not-ready")).toHaveCount(0);

  // the groups move on: the old result stays, marked as made for an older version, with a way to look again
  await sql("UPDATE grow_run SET basis_ref = 'an older version' WHERE business_id = $1", [venue.businessId]);
  await page.reload();
  await expect(page.getByTestId("stale")).toContainText("older version of your groups");
  await expect(page.getByTestId("ghosts")).toBeVisible();
  await expect(page.getByTestId("ask")).toBeVisible();

  // a failed look-up says why and offers another
  await sql("UPDATE grow_run SET status = 'failed', result = NULL, error = 'Qloo gave no neighbouring acts for any of your groups, so there is nothing to build on yet.' WHERE business_id = $1", [venue.businessId]);
  await page.reload();
  await expect(page.getByTestId("not-ready")).toHaveAttribute("data-state", "failed");
  await expect(page.getByTestId("not-ready")).toContainText("no neighbouring acts");
  await expect(page.getByTestId("ask")).toContainText("Try again");
  await shot(page, info, "grow-failed");
  await a11y(page, "grow failed");
  expect(problems.filter((p) => !prefetch.test(p))).toEqual([]);
});

test("grow: ghost customers name the genre, the genre it sits next to, the acts, and never a count under ten", async ({ page, request }, info) => {
  test.setTimeout(300_000);
  const problems = watch(page);
  const venue = await publishedVenue(request);
  await plantCrowd(venue.businessId, venue.qrId, 90, 6);
  await fitted(venue.businessId);
  const { groups } = await plantGrow(venue.tenantId, venue.businessId, "crowd");
  await signIn(page, venue.email);
  await page.goto("/app/grow");

  await expect(page.getByTestId("basis")).toContainText("provisional");
  const ghosts = page.getByTestId("ghosts");
  await expect(ghosts).toHaveAttribute("data-status", "ok");
  await expect(ghosts.getByRole("heading", { name: "Who else might come", level: 2 })).toBeVisible();
  await expect(ghosts.locator(".lbl")).toContainText("Modelled");
  await expect(page.getByTestId("ghost-check")).toContainText("0% in common");
  await expect(page.getByTestId("ghost-group")).toHaveCount(groups.length);
  await expect(page.getByTestId("ghost")).toHaveCount(groups.length);
  const first = page.getByTestId("ghost").first();
  await expect(first).toContainText("Shoegaze");
  await expect(first).toContainText("sits next to Indie");
  await expect(first.getByTestId("ghost-carrying")).toContainText("Fewer than 10 of your guests pick it.");
  await expect(first.getByTestId("ghost-act")).toHaveCount(3);
  // a count of ten or more may be shown
  await expect(page.getByTestId("ghost-carrying").nth(1)).toContainText("14 of your guests pick it.");
  // an act opens Soundcheck with its name already typed in
  await expect(first.getByTestId("ghost-act").first().getByRole("link")).toHaveAttribute("href", /\/app\/soundcheck\?q=Neighbour/);

  await page.getByText("How this is worked out").first().click();
  await expect(page.getByText(/a genre is a ghost when at least 2 of those acts carry it/i)).toBeVisible();
  await expect(page.getByText(/A count under 10 is never shown as a number/)).toBeVisible();

  // places matched to the crowd as a whole, with the checks printed beside them
  const nearby = page.getByTestId("nearby");
  await expect(nearby).toHaveAttribute("data-mode", "taste");
  await expect(nearby.locator(".lbl")).toContainText("Modelled");
  await expect(page.getByTestId("nearby-note")).toContainText("mostly the same places");
  await expect(page.getByTestId("nearby-check")).toContainText("changed 67% of its first ten places");
  await expect(page.getByTestId("nearby-check")).toContainText("59% in common");
  await expect(nearby.getByTestId("place")).toHaveCount(5);
  await expect(nearby.getByTestId("nearby-group")).toHaveCount(0);
  await expect(nearby.getByTestId("gap")).toHaveCount(0);
  const elsewhere = page.getByTestId("elsewhere");
  await expect(elsewhere.getByTestId("place").first()).toContainText("1.3 km");
  await expect(page.getByTestId("places-foot")).toContainText("not independently confirmed");

  // the Qloo calls behind the run open on request (none were planted, so the list is empty and says so)
  await page.getByTestId("calls-disc").locator("summary").click();
  await expect(page.getByTestId("calls-disc")).toContainText("0 calls");

  await shot(page, info, "grow-ready");
  await a11y(page, "grow ready");
  await setTheme(page, "dark");
  await shot(page, info, "grow-ready", "dark");
  await a11y(page, "grow ready dark");
  await setTheme(page, "light");
  expect(problems.filter((p) => !prefetch.test(p))).toEqual([]);
});

test("grow: groups told apart get their own places, a group with none is a gap candidate, and a list that ignored the crowd is only near you", async ({ page, request }, info) => {
  test.setTimeout(300_000);
  const problems = watch(page);
  const venue = await publishedVenue(request);
  await plantCrowd(venue.businessId, venue.qrId, 90, 7);
  await fitted(venue.businessId);
  const { groups } = await plantGrow(venue.tenantId, venue.businessId, "apart");
  await signIn(page, venue.email);
  await page.goto("/app/grow");

  const nearby = page.getByTestId("nearby");
  await expect(nearby).toHaveAttribute("data-mode", "taste");
  await expect(page.getByTestId("nearby-note")).toContainText("each group is listed on its own");
  await expect(nearby.getByTestId("nearby-group")).toHaveCount(groups.length);
  await expect(nearby.getByTestId("gap")).toHaveCount(1);
  await expect(nearby.getByTestId("gap")).toContainText("No place of its own among Qloo’s first ten");
  await expect(page.getByTestId("elsewhere").getByTestId("elsewhere-group")).toHaveCount(groups.length);
  await expect(page.getByTestId("places-foot")).toContainText("1 marked closed was left out");
  await shot(page, info, "grow-apart");
  await a11y(page, "grow apart");
  await setTheme(page, "dark");
  await shot(page, info, "grow-apart", "dark");
  await a11y(page, "grow apart dark");
  await setTheme(page, "light");

  await plantGrow(venue.tenantId, venue.businessId, "near");
  await page.reload();
  await expect(page.getByTestId("nearby")).toHaveAttribute("data-mode", "near");
  await expect(page.getByTestId("nearby").locator(".lbl")).toContainText("Observed");
  await expect(page.getByTestId("nearby-note")).toContainText("places near you, not places matched to your crowd");
  await expect(page.getByTestId("nearby-check")).toContainText("changed 0% of its first ten places");
  await expect(page.getByTestId("nearby").getByTestId("nearby-group")).toHaveCount(0);
  await expect(page.getByTestId("elsewhere-note")).toContainText("not lookalikes of your venue");
  // a group Qloo could not answer for is named, not silently dropped
  await expect(page.getByTestId("ghost-skipped")).toContainText("did not give an answer that depended on this group");
  await shot(page, info, "grow-near");
  await a11y(page, "grow near");

  await plantGrow(venue.tenantId, venue.businessId, "no_ghosts");
  await page.reload();
  await expect(page.getByTestId("ghosts")).toHaveAttribute("data-status", "not_group_specific");
  await expect(page.getByTestId("ghosts")).toContainText("mostly the same neighbouring acts");
  await expect(page.getByTestId("ghost")).toHaveCount(0);
  await expect(page.getByTestId("places-unavailable")).toContainText("bar, live music venue, cafe, restaurant or hotel bar");
  await shot(page, info, "grow-no-ghosts");
  await a11y(page, "grow no ghosts");
  expect(problems.filter((p) => !prefetch.test(p))).toEqual([]);
});
