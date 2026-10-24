import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";
import { plantRealCrowds, publishedVenue, resetRateLimits, setTheme, shot, signIn, sql, watch } from "./helpers";

// Real Qloo, real picker, real card. Spends about a dozen calls of quota, so it only runs on request.
test.skip(process.env.NIGIWAI_E2E_LIVE !== "1", "set NIGIWAI_E2E_LIVE=1 to spend Qloo quota");

test("a guest picks real things with live search and gets a real fill-in on the card", async ({ page, request }, info) => {
  test.setTimeout(120_000);
  await resetRateLimits();
  const problems = watch(page);
  const venue = await publishedVenue(request, { reward: { title: "A free coffee", detail: "At the bar." } });
  await page.goto(`/s/${venue.token}`);
  await page.getByRole("button", { name: "Start" }).click();

  for (const [query, expected] of [
    ["radiohead", /Radiohead/],
    ["normal people", /Normal People/],
    ["blue bottle", /Blue Bottle/],
  ] as const) {
    await page.getByLabel("Search", { exact: true }).fill(query);
    const first = page.getByRole("button", { name: expected }).filter({ hasText: "Add" }).first();
    await expect(first).toBeVisible({ timeout: 20_000 });
    await first.click();
    await expect(page.getByRole("button", { name: /^Remove / }).first()).toBeVisible();
  }
  await shot(page, info, "live-picked");
  await page.getByRole("button", { name: "Continue" }).click();
  await page.getByRole("button", { name: "Send my picks" }).click();

  await expect(page.getByRole("heading", { level: 1 })).toContainText("still forming");
  await expect(page.getByText("Finding related tastes…")).toBeHidden({ timeout: 40_000 });
  await expect(page.getByText(/Because you picked/).first()).toBeVisible();
  await expect(page.getByRole("heading", { name: "Places near here" })).toBeVisible();
  await shot(page, info, "live-card");
  await page.evaluate(() => window.scrollTo(0, document.body.scrollHeight));
  await page.locator(".s-main").evaluate((el) => el.scrollTo(0, 700));
  await shot(page, info, "live-card-extras");
  expect((await new AxeBuilder({ page }).analyze()).violations).toEqual([]);
  await setTheme(page, "dark");
  await shot(page, info, "live-card-extras", "dark");
  expect((await new AxeBuilder({ page }).analyze()).violations).toEqual([]);
  expect(problems).toEqual([]);
});

test("public lineups for a real venue: real MusicBrainz, real Qloo matching", async ({ page, request }, info) => {
  test.setTimeout(300_000);
  await resetRateLimits();
  const problems = watch(page);
  const venue = await publishedVenue(request);
  await signIn(page, venue.email);
  await page.locator(".shell__main").waitFor(); // the shell renders once the session has loaded
  const menu = page.getByRole("button", { name: "Menu" });
  if (await menu.isVisible()) await menu.click();
  await page.getByRole("navigation", { name: "Pages" }).getByRole("link", { name: "My people" }).click();
  await page.getByLabel("Venue name").fill("Mercury Lounge");
  await page.getByRole("button", { name: "Search" }).click();
  await expect(page.getByRole("list", { name: "Matching venues" })).toBeVisible({ timeout: 30_000 });
  await page.getByRole("listitem").filter({ hasText: "Lower East Side" }).getByRole("button", { name: "Use this venue" }).click();
  await expect(page.getByText(/acts matched in Qloo/)).toBeVisible({ timeout: 280_000 });
  await shot(page, info, "live-lineup");
  expect((await new AxeBuilder({ page }).analyze()).violations).toEqual([]);
  expect(problems).toEqual([]);
});

const REAL_CROWDS = {
  pop: ["Dua Lipa", "Olivia Rodrigo", "Billie Eilish", "Sabrina Carpenter", "Charli XCX", "Gracie Abrams", "Doja Cat", "Taylor Swift"],
  crooners: ["Frank Sinatra", "Bing Crosby", "Dean Martin", "Tony Bennett", "Nat King Cole", "Perry Como", "Ella Fitzgerald", "Louis Armstrong"],
  metal: ["Metallica", "Iron Maiden", "Slayer", "Pantera", "Black Sabbath", "Judas Priest", "Megadeth", "Anthrax"],
};

test("my people reads a real audience for each group from Qloo, and says what it is", async ({ page, request }, info) => {
  test.setTimeout(420_000);
  await resetRateLimits();
  const problems = watch(page);
  const venue = await publishedVenue(request);

  // Resolve real artists through the public picker, a sitting per crowd (a sitting may make 20 live searches).
  const crowds: { id: string; urn: string }[][] = [];
  for (const acts of Object.values(REAL_CROWDS)) {
    const view = await (await request.get(`/api/v1/public/survey/${venue.token}`)).json();
    const ids: { id: string; urn: string }[] = [];
    for (const act of acts) {
      const found = await (
        await request.post("/api/v1/public/picker", { data: { token: venue.token, nonce: view.nonce, q: act, type: "artist" } })
      ).json();
      const top = found.items?.[0];
      if (!top || top.name.normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase() !== act.toLowerCase()) continue;
      const sel = await (
        await request.post("/api/v1/public/select", { data: { token: venue.token, nonce: view.nonce, entity_id: top.entity_id } })
      ).json();
      if (sel.eligible) ids.push({ id: top.entity_id, urn: "urn:entity:artist" });
    }
    expect(ids.length).toBeGreaterThanOrEqual(6);
    crowds.push(ids);
  }
  await plantRealCrowds(venue.qrId, venue.businessId, crowds, 75, 11);
  await sql("UPDATE job SET run_after = now() WHERE business_id = $1", [venue.businessId]);

  await signIn(page, venue.email);
  await page.locator(".shell__main").waitFor();
  const menu = page.getByRole("button", { name: "Menu" });
  if (await menu.isVisible()) await menu.click();
  await page.getByRole("navigation", { name: "Pages" }).getByRole("link", { name: "My people" }).click();
  await expect(page.getByRole("heading", { name: "Forming groups" }).first()).toBeVisible({ timeout: 150_000 });
  await expect(page.locator(".tribe-card")).toHaveCount(3);

  const readings = page.getByTestId(/^audience-/);
  await expect(readings).toHaveCount(3);
  for (let i = 0; i < 3; i++) await expect(readings.nth(i)).toContainText("Read from Qloo’s audience data", { timeout: 30_000 });
  const text = (await readings.allInnerTexts()).join(" | ");
  expect(text).toMatch(/Younger-leaning/);
  expect(text).toMatch(/Older-leaning/);
  expect(text).toMatch(/Leans women/);
  expect(text).toMatch(/Leans men/);
  expect(text).toContain("not verified");
  await readings.first().scrollIntoViewIfNeeded();
  await page.locator(".tribe-card").first().screenshot({ path: `e2e-shots/${info.project.name}-light-audience-card.png` });
  await page.evaluate(() => window.scrollBy(0, 500));
  await shot(page, info, "audience-scrolled"); // a plain viewport picture, as a person scrolling would see it
  expect((await new AxeBuilder({ page }).analyze()).violations).toEqual([]);
  await setTheme(page, "dark");
  await page.waitForTimeout(450);
  await page.locator(".tribe-card").first().screenshot({ path: `e2e-shots/${info.project.name}-dark-audience-card.png` });
  expect((await new AxeBuilder({ page }).analyze()).violations).toEqual([]);
  expect(problems).toEqual([]);
});
