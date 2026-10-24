import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page } from "@playwright/test";
import { fridayAgo, plantCrowd, plantDated, publishedVenue, resetRateLimits, setTheme, shot, signIn, sql, watch } from "./helpers";

test.beforeEach(async () => resetRateLimits());

async function a11y(page: Page, label: string) {
  const result = await new AxeBuilder({ page }).analyze();
  expect(result.violations.map((v) => `${label}: ${v.id} ${v.nodes.map((n) => n.html.slice(0, 120)).join(" | ")}`)).toEqual([]);
}
const prefetch = /requestfailed: GET \S+\?_rsc=\S+ net::ERR_ABORTED/;

test("moves: log a change, see scans in the same slot before and after with their uncertainty, change it, remove it", async ({ page, request }, info) => {
  test.setTimeout(150_000);
  const problems = watch(page);
  const venue = await publishedVenue(request);
  await plantCrowd(venue.businessId, venue.qrId, 44, 7);
  // 2 scans on each of the four Fridays before, 10 on each of three after, and 6 at Friday lunchtime (outside the slot)
  await plantDated(venue.qrId, [
    ...[7, 6, 5, 4].map((w) => [fridayAgo(w), 19, 2] as [string, number, number]),
    ...[3, 2, 1].map((w) => [fridayAgo(w), 19, 10] as [string, number, number]),
    [fridayAgo(2), 12, 6],
  ]);
  await signIn(page, venue.email);
  await page.goto("/app/moves");

  await expect(page.getByRole("heading", { name: "Moves", level: 1 })).toBeVisible();
  await expect(page.getByTestId("empty")).toBeVisible();
  await shot(page, info, "moves-empty");
  await a11y(page, "moves empty");

  // a form that is wrong says why and keeps what was typed
  await page.getByTestId("new-move").click();
  await expect(page.getByTestId("move-form")).toBeVisible();
  await page.getByRole("button", { name: "Log this move" }).click();
  await expect(page.locator(".banner[data-tone='error']")).toContainText("Say what changed.");
  await page.getByLabel("What changed").fill("Booked The Quiet Engines for Friday evenings");
  await page.getByLabel("Started on").fill(fridayAgo(3));
  await page.getByLabel(/Ended on/).fill(fridayAgo(5));
  await page.getByRole("button", { name: "Log this move" }).click();
  await expect(page.locator(".banner[data-tone='error']")).toContainText("The end date cannot be before the start date.");
  await page.getByLabel(/Ended on/).fill("");

  // aimed at Friday evenings only
  await page.getByRole("button", { name: "Fri", exact: true }).click();
  await expect(page.getByText("Only these days are compared.")).toBeVisible();
  await page.getByLabel("All hours you are open").uncheck();
  await page.getByLabel("From", { exact: true }).selectOption("18");
  await page.getByLabel("To", { exact: true }).selectOption("22");
  await page.getByLabel("A note (optional)").fill("A trial month.");
  await shot(page, info, "moves-form");
  await a11y(page, "moves form");
  await page.getByRole("button", { name: "Log this move" }).click();

  const card = page.getByTestId("move").filter({ hasText: "Booked The Quiet Engines for Friday evenings" });
  await expect(card).toBeVisible();
  await expect(card.getByTestId("verdict")).toHaveText("More scans");
  await expect(card).toContainText("Friday 18:00 to 22:00");
  await expect(card).toContainText("A trial month.");
  await expect(card.getByTestId("numbers")).toContainText("8 scans before");
  await expect(card.getByTestId("numbers")).toContainText("30 scans after");
  await expect(card.getByTestId("ratio")).toContainText("90% range");
  await expect(card.getByTestId("text")).toContainText("does not show the change caused it");
  await expect(page.getByTestId("ledger")).toContainText("1 move: 1 with more scans");
  expect((await sql("SELECT weekdays, hour_from, hour_to FROM move WHERE business_id = $1", [venue.businessId])).rows[0]).toEqual({ weekdays: [4], hour_from: 18, hour_to: 22 });
  await shot(page, info, "moves-result");
  await a11y(page, "moves result");
  await setTheme(page, "dark");
  await shot(page, info, "moves-result", "dark");
  await a11y(page, "moves result dark");
  await setTheme(page, "light");

  // a change that has only just begun is too early to judge
  await page.getByTestId("new-move").click();
  await page.getByLabel("What changed").fill("A new weekend menu");
  await page.getByLabel("What kind of change").selectOption("menu");
  await page.getByRole("button", { name: "Log this move" }).click();
  const newer = page.getByTestId("move").filter({ hasText: "A new weekend menu" });
  await expect(newer.getByTestId("verdict")).toHaveText("Too early to say");
  await expect(page.getByTestId("ledger")).toContainText("2 moves: 1 with more scans, 0 with fewer, 0 inconclusive, 1 too early to say");

  // change the first one
  await card.getByRole("button", { name: "Change" }).click();
  await expect(page.getByLabel("What changed")).toHaveValue("Booked The Quiet Engines for Friday evenings");
  await page.getByLabel("What changed").fill("Residency: The Quiet Engines, Fridays");
  await page.getByRole("button", { name: "Save changes" }).click();
  await expect(page.getByTestId("move").filter({ hasText: "Residency: The Quiet Engines, Fridays" })).toBeVisible();

  // remove the menu move: it asks first
  await newer.getByRole("button", { name: "Remove", exact: true }).click();
  await newer.getByRole("button", { name: "Keep it" }).click();
  await expect(newer).toBeVisible();
  await newer.getByRole("button", { name: "Remove", exact: true }).click();
  await newer.getByRole("button", { name: "Remove it" }).click();
  await expect(page.getByTestId("move")).toHaveCount(1);
  expect((await sql("SELECT count(*)::int AS n FROM move WHERE business_id = $1", [venue.businessId])).rows[0]?.n).toBe(1);

  // after a reload the same results are worked out again from the stored scans
  await page.reload();
  await expect(page.getByTestId("move")).toHaveCount(1);
  await expect(page.getByTestId("move").first().getByTestId("verdict")).toHaveText("More scans");
  expect(problems.filter((p) => !prefetch.test(p) && !/422/.test(p))).toEqual([]);
});

test("moves: a small difference in few scans is called inconclusive, and the menu shows the page when the plan keeps it", async ({ page, request }, info) => {
  test.setTimeout(120_000);
  const problems = watch(page);
  const venue = await publishedVenue(request);
  await plantCrowd(venue.businessId, venue.qrId, 12, 8);
  await plantDated(venue.qrId, [
    ...[7, 6, 5, 4].map((w) => [fridayAgo(w), 19, 1] as [string, number, number]),
    ...[3, 2].map((w) => [fridayAgo(w), 19, 4] as [string, number, number]),
  ]);
  await signIn(page, venue.email);
  await page.goto("/app/moves");
  await page.getByTestId("new-move").click();
  await page.getByLabel("What changed").fill("Two acts a month");
  await page.getByLabel("Started on").fill(fridayAgo(3));
  await page.getByRole("button", { name: "Fri", exact: true }).click();
  await page.getByRole("button", { name: "Log this move" }).click();
  // every hour is compared here, so the lunchtime-free planted scans all count
  const card = page.getByTestId("move").first();
  await expect(card.getByTestId("verdict")).toHaveText("Inconclusive");
  await expect(card.getByTestId("text")).toContainText("within what chance alone produces");
  await shot(page, info, "moves-inconclusive");
  await a11y(page, "moves inconclusive");
  await page.goto("/app");
  await page.locator(".shell__main").waitFor(); // the shell renders once the session has loaded
  const menu = page.getByRole("button", { name: "Menu" });
  if (await menu.isVisible()) await menu.click();
  await expect(page.getByRole("navigation", { name: "Pages" }).getByRole("link", { name: "Moves" })).toBeVisible();
  expect(problems.filter((p) => !prefetch.test(p))).toEqual([]);
});
