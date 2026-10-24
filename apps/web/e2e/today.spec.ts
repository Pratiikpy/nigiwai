import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page } from "@playwright/test";
import { openAllWeek, plantCrowd, plantLineup, plantSuggestions, publishedVenue, resetRateLimits, setRhythm, setTheme, shot, signIn, sql, watch } from "./helpers";

test.beforeEach(async () => resetRateLimits());

async function a11y(page: Page, label: string) {
  const result = await new AxeBuilder({ page }).analyze();
  expect(result.violations.map((v) => `${label}: ${v.id} ${v.nodes.map((n) => n.html.slice(0, 120)).join(" | ")}`)).toEqual([]);
}

const prefetch = /requestfailed: GET \S+[?&]_rsc=\S+ net::ERR_ABORTED/;

test("today: a new venue sees how to start, and the opening hours are set on Your venue", async ({ page, request }, info) => {
  const problems = watch(page);
  const venue = await publishedVenue(request);
  await signIn(page, venue.email);
  await page.goto("/app/today");
  await expect(page.getByRole("heading", { name: "Today", level: 1 })).toBeVisible();
  await expect(page.getByTestId("day0")).toBeVisible();
  await expect(page.getByRole("heading", { name: "Your board wakes up with your first scans." })).toBeVisible();
  await expect(page.getByTestId("scans")).toHaveText("0");
  await expect(page.getByText("Your first quiet-hours picture at 10 scans")).toBeVisible();
  await expect(page.getByTestId("actions")).toHaveCount(0);
  // the layout, not only the words: the steps use the card's width (a leftover two-column rule once squeezed them into 220 px)
  const box = await page.getByTestId("day0").locator("> .stack").boundingBox();
  const card = await page.getByTestId("day0").boundingBox();
  expect(box!.width).toBeGreaterThan(card!.width * 0.7);
  await shot(page, info, "today-day0");
  await a11y(page, "today day0");
  await setTheme(page, "dark");
  await shot(page, info, "today-day0", "dark");
  await a11y(page, "today day0 dark");

  // opening hours: tick Monday, copy it to the week, break one day, see the refusal, fix it, save
  await page.goto("/app/venue");
  const hours = page.getByTestId("hours");
  await expect(hours.getByText("Closed", { exact: true })).toHaveCount(7);
  await hours.getByLabel("Monday").check();
  await hours.getByRole("button", { name: "Copy the first open day to every day" }).click();
  await expect(hours.getByText("Closed", { exact: true })).toHaveCount(0);
  await hours.getByLabel("Sunday closes").fill("12:00"); // opens 12:00 too: no span
  await page.getByRole("button", { name: "Save" }).click();
  await expect(page.getByRole("alert").filter({ hasText: /differ/i })).toBeVisible();
  await hours.getByLabel("Sunday closes").fill("02:00"); // after midnight is allowed
  await page.getByRole("button", { name: "Save" }).click();
  await expect(page.getByText("Saved.")).toBeVisible();
  const saved = (await sql<{ hours: unknown }>("SELECT hours FROM location WHERE business_id = $1", [venue.businessId])).rows[0]?.hours as { open: string; close: string }[];
  expect(saved).toHaveLength(7);
  expect(saved[0]).toEqual({ open: "12:00", close: "23:00" });
  expect(saved[6]).toEqual({ open: "12:00", close: "02:00" });
  await a11y(page, "venue hours");
  await shot(page, info, "venue-hours");
  expect(problems.filter((p) => !/422/.test(p) && !prefetch.test(p))).toEqual([]);
});

test("today: a real week of scans shows the quietest stretch, two actions with labelled evidence, and decisions that stay", async ({ page, request }, info) => {
  test.setTimeout(180_000);
  const problems = watch(page);
  const venue = await publishedVenue(request);
  await plantCrowd(venue.businessId, venue.qrId, 90);
  await setRhythm(venue.qrId);
  await openAllWeek(venue.businessId);
  await plantLineup(venue.tenantId, venue.businessId, { events: 40 });
  await plantSuggestions(venue.tenantId, venue.businessId, [
    { name: "Velvet Harbour", score: 88, best: "Indie rock acts" },
    { name: "The Quiet Engines", score: 81, best: "Jazz acts" },
  ]);
  await signIn(page, venue.email);
  await page.goto("/app/today");

  await expect(page.getByTestId("scans")).toHaveText("90");
  const quiet = page.getByTestId("quiet");
  await expect(quiet).toBeVisible();
  await expect(quiet.getByText("Wednesday 14:00 to 17:00")).toBeVisible();
  await expect(quiet.getByText("0 scans")).toBeVisible();
  // the heat map is a table a screen reader can read cell by cell
  await expect(page.getByRole("cell", { name: "Wednesday 15:00, 0 scans" })).toBeVisible();
  await expect(page.getByRole("cell", { name: "Friday 19:00, 5 scans" })).toBeVisible();

  const actions = page.getByTestId("action");
  await expect(actions).toHaveCount(2);
  const fill = actions.nth(0);
  const book = actions.nth(1);
  await expect(fill.getByRole("heading", { name: "Try Velvet Harbour on Wednesday 14:00 to 17:00" })).toBeVisible();
  await expect(fill.getByLabel("Evidence").getByText("Measured").first()).toBeVisible();
  await expect(fill).toContainText("0 of 90 scans came on Wednesday 14:00 to 17:00");
  await expect(fill.getByTestId("fit")).toContainText("88");
  await expect(fill.getByTestId("fit")).toContainText("Likely range 83 to 92");
  await expect(book.getByRole("heading", { name: "Book The Quiet Engines for Friday evening" })).toBeVisible();
  await expect(book).toContainText("15 of 90 scans came on Friday 18:00 to 21:00");
  await expect(book).toContainText("Qloo has no event listings");
  await shot(page, info, "today-full");
  await a11y(page, "today full");
  await setTheme(page, "dark");
  await shot(page, info, "today-full", "dark");
  await a11y(page, "today full dark");
  await setTheme(page, "light");

  // an action leads to Ask Nigiwai with the question ready to send
  await fill.getByRole("link", { name: "Ask Nigiwai about this" }).click();
  await expect(page).toHaveURL(/\/app\/ask\?mode=crowd&q=/);
  await expect(page.getByLabel("Your question")).toHaveValue("Would Velvet Harbour suit my crowd, and would it clash with anyone?");
  await expect(page.getByRole("button", { name: "About my crowd" })).toHaveAttribute("aria-pressed", "true");
  await page.goBack();
  await expect(page.getByTestId("action").first()).toBeVisible();

  // accept: it can be logged as a move, once
  await fill.getByRole("button", { name: "Accept" }).click();
  await expect(fill).toHaveAttribute("data-state", "accepted");
  await expect(fill.getByText("Accepted.")).toBeVisible();
  await fill.getByRole("button", { name: "Log this move" }).click();
  await expect(fill.getByRole("button", { name: "Logged as a move" })).toBeDisabled();
  expect((await sql("SELECT count(*)::int AS n FROM move WHERE business_id = $1", [venue.businessId])).rows[0]?.n).toBe(1);
  // the move is on the Moves page with the slot the action was about, and says it is too early to judge
  await fill.getByRole("link", { name: "See it on Moves" }).click();
  await expect(page.getByRole("heading", { name: "Moves", level: 1 })).toBeVisible();
  const logged = page.getByTestId("move");
  await expect(logged).toHaveCount(1);
  await expect(logged).toContainText("Try Velvet Harbour on Wednesday 14:00 to 17:00");
  await expect(logged).toContainText("Wednesday 14:00 to 17:00");
  await expect(logged).toContainText("logged from Today");
  await expect(logged.getByTestId("verdict")).toHaveText("Too early to say");
  await page.goBack();
  await expect(page.getByTestId("action").first()).toBeVisible();
  // dismiss the other, then undo, then dismiss again
  await book.getByRole("button", { name: "Not now" }).click();
  await expect(actions.nth(1)).toHaveAttribute("data-state", "dismissed");
  await actions.nth(1).getByRole("button", { name: "Undo" }).click();
  await expect(actions.nth(1)).toHaveAttribute("data-state", "open");
  await actions.nth(1).getByRole("button", { name: "Not now" }).click();
  await expect(actions.nth(1)).toHaveAttribute("data-state", "dismissed");
  await shot(page, info, "today-decided");
  await a11y(page, "today decided");

  // the decisions are still there after a reload
  await page.reload();
  await expect(page.getByTestId("action").nth(0)).toHaveAttribute("data-state", "accepted");
  await expect(page.getByTestId("action").nth(0).getByRole("button", { name: "Logged as a move" })).toBeVisible();
  await expect(page.getByTestId("action").nth(1)).toHaveAttribute("data-state", "dismissed");
  expect(problems.filter((p) => !prefetch.test(p))).toEqual([]);
});

test("today: a few scans draw an early hours picture but promise nothing, and say what would unlock more", async ({ page, request }, info) => {
  test.setTimeout(120_000);
  const problems = watch(page);
  const venue = await publishedVenue(request);
  await plantCrowd(venue.businessId, venue.qrId, 12);
  await openAllWeek(venue.businessId);
  // twelve scans, all in open hours, on three different days
  const ids = (await sql<{ id: string }>("SELECT id FROM response WHERE qr_point_id = $1 ORDER BY id", [venue.qrId])).rows;
  for (const [i, r] of ids.entries()) {
    await sql("UPDATE response SET local_weekday = $1, local_hour = $2 WHERE id = $3", [(i % 3) + 1, 13 + (i % 5), r.id]);
  }
  await signIn(page, venue.email);
  await page.goto("/app/today");
  await expect(page.getByTestId("scans")).toHaveText("12");
  await expect(page.getByTestId("thin")).toBeVisible();
  await expect(page.getByRole("heading", { name: "Not enough data yet to suggest anything" })).toBeVisible();
  await expect(page.getByText("Early look.")).toBeVisible();
  await expect(page.getByTestId("quiet")).toHaveCount(0); // too few scans to name a quiet stretch
  await expect(page.getByText("Your quietest hours named from 20 scans")).toBeVisible();
  await expect(page.getByText("8 more scans.").first()).toBeVisible();
  await expect(page.getByTestId("action")).toHaveCount(0);
  await shot(page, info, "today-thin");
  await a11y(page, "today thin");
  expect(problems.filter((p) => !prefetch.test(p))).toEqual([]);
});

test("today: without opening hours nothing is called quiet and the board asks for them", async ({ page, request }, info) => {
  test.setTimeout(120_000);
  const problems = watch(page);
  const venue = await publishedVenue(request);
  await plantCrowd(venue.businessId, venue.qrId, 90);
  await setRhythm(venue.qrId);
  await signIn(page, venue.email);
  await page.goto("/app/today");
  await expect(page.getByTestId("scans")).toHaveText("90");
  await expect(page.getByText("Say when you are open.")).toBeVisible();
  await expect(page.getByRole("link", { name: "Add them on Your venue" })).toBeVisible();
  await expect(page.getByTestId("quiet")).toHaveCount(0);
  await shot(page, info, "today-no-hours");
  await a11y(page, "today no hours");
  expect(problems.filter((p) => !prefetch.test(p))).toEqual([]);
});

test("today: a cafe is offered an idea for its quietest stretch from its own scans and its biggest group's picks, with no act, and can log it as a move", async ({ page, request }, info) => {
  test.setTimeout(240_000);
  const problems = watch(page);
  const venue = await publishedVenue(request);
  await plantCrowd(venue.businessId, venue.qrId, 90);
  await setRhythm(venue.qrId);
  await openAllWeek(venue.businessId);
  await sql("UPDATE business SET type = 'cafe' WHERE id = $1", [venue.businessId]);
  await sql("UPDATE job SET run_after = now() WHERE business_id = $1", [venue.businessId]);
  await expect
    .poll(async () => (await sql("SELECT state FROM tribe_version WHERE business_id = $1 ORDER BY version DESC LIMIT 1", [venue.businessId])).rows[0]?.state, { timeout: 120_000 })
    .toMatch(/provisional|named/);
  await signIn(page, venue.email);
  await page.goto("/app/today");

  const actions = page.getByTestId("action");
  await expect(actions).toHaveCount(1);
  const idea = actions.first();
  await expect(idea.getByRole("heading", { name: "Aim something at Wednesday afternoon" })).toBeVisible();
  await expect(idea).toContainText("Wednesday 14:00 to 17:00 is your quietest stretch");
  await expect(idea).toContainText("% of the guests who answered");
  await expect(idea).toContainText("0 of 90 scans came on Wednesday 14:00 to 17:00");
  await expect(idea).toContainText("a hypothesis, not a forecast");
  const labels = await idea.getByLabel("Evidence").locator(".lbl__t").allInnerTexts();
  expect(labels).toEqual(["Measured", "Measured", "Modelled"]);
  await expect(idea.getByTestId("fit")).toHaveCount(0); // no act, so no fit to show
  await expect(idea.getByRole("link", { name: "Soundcheck this act" })).toHaveCount(0);
  await expect(idea.getByRole("link", { name: "Ask Nigiwai about this" })).toBeVisible();
  await expect(page.getByRole("heading", { name: /Book .* for/ })).toHaveCount(0);
  await shot(page, info, "today-cafe");
  await a11y(page, "today cafe");
  await setTheme(page, "dark");
  await shot(page, info, "today-cafe", "dark");
  await a11y(page, "today cafe dark");
  await setTheme(page, "light");

  await idea.getByRole("button", { name: "Accept" }).click();
  await expect(idea).toContainText("Accepted.");
  await expect(idea.getByRole("link", { name: "Prepare drafts" })).toHaveCount(0); // drafts are about an act
  await idea.getByRole("button", { name: "Log this move" }).click();
  await expect(idea.getByRole("button", { name: "Logged as a move" })).toBeVisible();
  expect((await sql("SELECT weekdays, hour_from, hour_to FROM move WHERE business_id = $1", [venue.businessId])).rows).toEqual([{ weekdays: [2], hour_from: 14, hour_to: 17 }]);
  expect(problems.filter((p) => !prefetch.test(p))).toEqual([]);
});
