import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page } from "@playwright/test";
import { plantNeighbourhood, publishedVenue, resetRateLimits, setTheme, shot, signIn, sql, watch } from "./helpers";

test.beforeEach(async () => resetRateLimits());

async function a11y(page: Page, label: string) {
  const result = await new AxeBuilder({ page }).analyze();
  expect(result.violations.map((v) => `${label}: ${v.id} ${v.nodes.map((n) => n.html.slice(0, 120)).join(" | ")}`)).toEqual([]);
}
const prefetch = /requestfailed: GET \S+\?_rsc=\S+ net::ERR_ABORTED/;

test("atlas: a venue that has not joined sees what joining shares and an example under a banner, joins only after agreeing, waits, and can leave", async ({ page, request }, info) => {
  test.setTimeout(240_000);
  const problems = watch(page);
  const venue = await publishedVenue(request);
  await signIn(page, venue.email);
  await page.goto("/app/atlas");
  await expect(page.getByRole("heading", { name: "City Taste Atlas", level: 1 })).toBeVisible();
  const status = page.getByTestId("atlas-status");
  await expect(status).toHaveAttribute("data-state", "not_joined");
  await expect(status).toContainText("Nothing of yours is shared");
  const terms = page.getByTestId("atlas-terms");
  await expect(terms).toContainText("Never shared: your venue’s name or address");
  await expect(terms).toContainText("a neighbourhood opens with 5 such venues");
  await expect(terms).toContainText("no one venue supplied more than 50%");
  await expect(page.getByTestId("atlas-join")).toBeDisabled();
  await expect(page.getByTestId("atlas-groups")).toHaveCount(0);

  await page.getByTestId("atlas-example-toggle").click();
  const example = page.getByTestId("example");
  await expect(example).toContainText("An example with invented data");
  await expect(example.getByTestId("atlas-item")).toHaveCount(5);
  await expect(example.getByTestId("atlas-own").first()).toContainText("18 of your guests picked it.");
  await expect(example.getByTestId("atlas-own").nth(1)).toContainText("Fewer than 10 of your guests picked it.");
  await shot(page, info, "atlas-not-joined");
  await a11y(page, "atlas not joined");
  await setTheme(page, "dark");
  await shot(page, info, "atlas-not-joined", "dark");
  await a11y(page, "atlas not joined dark");
  await setTheme(page, "light");

  await page.getByTestId("atlas-agree").check();
  await expect(page.getByTestId("atlas-join")).toBeEnabled();
  await page.getByTestId("atlas-join").click();
  await expect(status).toHaveAttribute("data-state", "waiting");
  await expect(status).toContainText("Not enough venues around you have joined yet");
  await expect(status).toContainText("at least 5");
  expect((await sql("SELECT atlas_opt_in FROM business WHERE id = $1", [venue.businessId])).rows[0]?.atlas_opt_in).toBe(true);
  await shot(page, info, "atlas-waiting");
  await a11y(page, "atlas waiting");
  await page.reload();
  await expect(page.getByTestId("atlas-status")).toHaveAttribute("data-state", "waiting"); // it stays joined

  await page.getByTestId("atlas-leave").click();
  await expect(page.getByTestId("atlas-status")).toHaveAttribute("data-state", "not_joined");
  expect((await sql("SELECT action FROM audit_log WHERE action LIKE 'atlas.%' AND target = $1 ORDER BY id", [venue.businessId])).rows.map((r) => r.action)).toEqual(["atlas.join", "atlas.leave"]);
  expect(problems.filter((p) => !prefetch.test(p))).toEqual([]);
});

test("atlas: with five venues in the neighbourhood the cell opens, lists only what meets the minimums, withholds small counts, and closes again when a venue leaves", async ({ page, request }, info) => {
  test.setTimeout(300_000);
  const problems = watch(page);
  const mine = await publishedVenue(request);
  const others = [await publishedVenue(request), await publishedVenue(request), await publishedVenue(request), await publishedVenue(request)];
  const tag = Date.now().toString(36);
  const planted = await plantNeighbourhood([mine, ...others], tag);
  const cell = { x: Math.floor(planted.lon * 100), y: Math.floor(planted.lat * 100) };
  const cellRows = async () => (await sql<{ n: number }>("SELECT count(*)::int AS n FROM atlas_cell WHERE cell_x = $1 AND cell_y = $2", [cell.x, cell.y])).rows[0]?.n ?? 0;

  await signIn(page, mine.email);
  await page.goto("/app/atlas");
  await expect(page.getByTestId("atlas-status")).toHaveAttribute("data-state", "not_joined");
  await page.getByTestId("atlas-agree").check();
  await page.getByTestId("atlas-join").click();
  // the worker rebuilds at once; the cell opens with the fifth venue
  await expect.poll(cellRows, { timeout: 60_000, intervals: [1000] }).toBe(2);
  await page.reload();
  await expect(page.getByTestId("atlas-status")).toHaveAttribute("data-state", "ready");
  await expect(page.getByTestId("atlas-basis")).toContainText("60 answers");
  const items = page.getByTestId("atlas-group").first().getByTestId("atlas-item");
  await expect(items).toHaveCount(2);
  await expect(items.first()).toContainText(`Sample act everyone ${tag}`);
  await expect(items.first()).toContainText("100% of answers · 60 guests · 5 venues");
  await expect(items.first().getByTestId("atlas-own")).toContainText("12 of your guests picked it.");
  await expect(items.nth(1)).toContainText(`Sample act three venues ${tag}`);
  await expect(items.nth(1)).toContainText("20% of answers · 12 guests · 3 venues");
  await expect(items.nth(1).getByTestId("atlas-own")).toContainText("Fewer than 10 of your guests picked it.");
  await expect(page.getByText(`Sample act nine ${tag}`)).toHaveCount(0); // nine answers: one short
  await expect(page.getByTestId("atlas-group").first().locator(".lbl")).toContainText("Measured");
  await expect(page.getByTestId("atlas-example-toggle")).toHaveCount(0);
  await shot(page, info, "atlas-ready");
  await a11y(page, "atlas ready");
  await setTheme(page, "dark");
  await shot(page, info, "atlas-ready", "dark");
  await a11y(page, "atlas ready dark");
  await setTheme(page, "light");

  await page.getByTestId("atlas-leave").click();
  await expect(page.getByTestId("atlas-status")).toHaveAttribute("data-state", "not_joined");
  await expect(page.getByTestId("atlas-groups")).toHaveCount(0);
  await expect.poll(cellRows, { timeout: 60_000, intervals: [1000] }).toBe(0); // four venues are not a neighbourhood
  expect(problems.filter((p) => !prefetch.test(p))).toEqual([]);
});
