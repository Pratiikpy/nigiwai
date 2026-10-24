import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Locator, type Page } from "@playwright/test";
import { openAllWeek, plantCrowd, plantPool, plantWeek, publishedVenue, resetRateLimits, setTheme, shot, signIn, sql, watch } from "./helpers";

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

test("sound plan: with no crowd it says what is missing; with groups but no scored acts it offers to build them", async ({ page, request }, info) => {
  test.setTimeout(240_000);
  const problems = watch(page);
  const venue = await publishedVenue(request);
  await signIn(page, venue.email);
  await page.goto("/app/sound");
  await expect(page.getByRole("heading", { name: "Sound plan", level: 1 })).toBeVisible();
  await expect(page.getByTestId("not-ready")).toHaveAttribute("data-state", "no_crowd");
  await expect(page.getByTestId("not-ready")).toContainText("Collect 60 guests");
  await expect(page.getByTestId("build")).toHaveCount(0);
  await expect(page.getByTestId("notes")).toContainText("Qloo recommends artists, not songs");
  await shot(page, info, "sound-empty");
  await a11y(page, "sound empty");

  await plantCrowd(venue.businessId, venue.qrId, 90, 5);
  await fitted(venue.businessId);
  await page.reload();
  await expect(page.getByTestId("not-ready")).toHaveAttribute("data-state", "needs_acts");
  await expect(page.getByTestId("build")).toBeVisible();
  await shot(page, info, "sound-needs-acts");
  await a11y(page, "sound needs acts");
  expect(problems.filter((p) => !prefetch.test(p))).toEqual([]);
});

test("sound plan: each stretch of the week names its own acts, says how busy it is, and leaves thin and closed stretches alone", async ({ page, request }, info) => {
  test.setTimeout(240_000);
  const problems = watch(page);
  const venue = await publishedVenue(request);
  await plantCrowd(venue.businessId, venue.qrId, 90, 6);
  // weekday evenings 36 scans, weekend evenings 40 (the busiest per hour), weekday afternoons 10, a few late ones
  await plantWeek(venue.qrId, [
    [0, 19, 9], [1, 19, 9], [2, 19, 9], [3, 19, 9],
    [4, 19, 14], [5, 19, 14], [6, 19, 12],
    [0, 14, 5], [1, 14, 5],
    [3, 23, 2], [4, 23, 2],
  ]);
  await openAllWeek(venue.businessId);
  await fitted(venue.businessId);
  await plantPool(venue.tenantId, venue.businessId, ["Amber Lanes", "Birch and Wire", "Cold Harbour", "Dune Parade", "Ember Choir", "Fallow Fields", "Garnet Row"]);
  await signIn(page, venue.email);
  await page.goto("/app/sound");

  await expect(page.getByTestId("basis")).toContainText("7 acts considered");
  await expect(page.getByTestId("cell")).toHaveCount(8);
  const evening = page.locator('[data-key="weekdays-evening"]');
  await expect(evening).toHaveAttribute("data-status", "ok");
  await expect(evening.getByTestId("act")).toHaveCount(5);
  await expect(evening.getByTestId("mix")).toContainText("Measured");
  await expect(evening.getByTestId("busy")).toBeVisible();
  await expect(evening.getByTestId("watch").first()).toContainText("Watch: ranks low for");
  const weekendEvening = page.locator('[data-key="weekend-evening"]');
  await expect(weekendEvening).toHaveAttribute("data-status", "ok");
  await expect(weekendEvening.getByTestId("busy")).toHaveAttribute("data-level", "busy"); // the busiest stretch of the planted week
  await expect(evening.getByTestId("busy")).toHaveAttribute("data-level", "steady");
  // each stretch is ranked best first
  const scores = async (cell: Locator) => (await cell.getByTestId("act").locator(".snd-acts__s .num").allInnerTexts()).map(Number);
  for (const cell of [evening, weekendEvening]) {
    const s = await scores(cell);
    expect(s).toEqual([...s].sort((a, b) => b - a));
  }
  // too few scans in the afternoon, and nothing before 12:00 (closed), so no acts are named there
  const afternoon = page.locator('[data-key="weekdays-afternoon"]');
  await expect(afternoon).toHaveAttribute("data-status", "thin");
  await expect(afternoon).toContainText("starts from 20");
  await expect(afternoon.getByTestId("act")).toHaveCount(0);
  await expect(page.locator('[data-key="weekdays-morning"]')).toHaveAttribute("data-status", "closed");
  await expect(page.locator('[data-key="weekdays-morning"]')).toContainText("You are not open in this stretch");
  await shot(page, info, "sound-plan");
  await a11y(page, "sound plan");
  await setTheme(page, "dark");
  await shot(page, info, "sound-plan", "dark");
  await a11y(page, "sound plan dark");
  await setTheme(page, "light");

  // the working is open to read, and the plan can be copied as text
  await page.getByText("How this is worked out").click();
  await expect(page.getByText("Score = 100 x group fit").first()).toBeVisible();
  await page.context().grantPermissions(["clipboard-read", "clipboard-write"]).catch(() => undefined);
  await page.getByRole("button", { name: "Copy as text" }).click();
  await expect(page.getByRole("button", { name: "Copied" })).toBeVisible();
  const text = await page.evaluate(() => navigator.clipboard.readText()).catch(() => null);
  if (text !== null) {
    expect(text).toContain("Sound plan");
    expect(text).toContain("Monday to Thursday");
    expect(text).toContain("not enough scans yet");
  }

  // an act opens Soundcheck with its name already typed into the search
  await evening.getByTestId("act").first().getByRole("link").click();
  await expect(page).toHaveURL(/\/app\/soundcheck\?q=/);
  await expect(page.getByRole("searchbox").or(page.locator("input[type='search']")).first()).toHaveValue(/\S/);
  // the side menu marks only the page it is on, though one name starts with the other
  const toggle = page.getByRole("button", { name: "Menu" });
  if (await toggle.isVisible()) await toggle.click(); // on a phone the menu is behind a button
  const current = page.getByRole("navigation", { name: "Pages" }).locator('a[aria-current="page"]');
  await expect(current).toHaveCount(1);
  await expect(current).toHaveText("Soundcheck");
  expect(problems.filter((p) => !prefetch.test(p))).toEqual([]);
});
