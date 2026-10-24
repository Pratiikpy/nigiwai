import AxeBuilder from "@axe-core/playwright";
import { expect, test, type APIRequestContext } from "@playwright/test";
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
  pop: [
    "Dua Lipa", "Olivia Rodrigo", "Billie Eilish", "Sabrina Carpenter", "Charli XCX", "Gracie Abrams", "Doja Cat", "Taylor Swift", "Lizzo", "Tate McRae",
    "Chappell Roan", "Conan Gray", "Lorde", "Halsey", "Selena Gomez", "Miley Cyrus", "Camila Cabello", "Demi Lovato", "Katy Perry", "Rihanna",
  ],
  crooners: [
    "Frank Sinatra", "Bing Crosby", "Dean Martin", "Tony Bennett", "Nat King Cole", "Perry Como", "Ella Fitzgerald", "Louis Armstrong", "Mel Torme", "Sammy Davis Jr.",
    "Andy Williams", "Billie Holiday", "Sarah Vaughan", "Nina Simone", "Judy Garland", "Doris Day", "Johnny Mathis", "Duke Ellington", "Count Basie", "Etta James",
  ],
  metal: [
    "Metallica", "Iron Maiden", "Slayer", "Pantera", "Black Sabbath", "Judas Priest", "Megadeth", "Anthrax", "Ozzy Osbourne", "Dio",
    "Deep Purple", "Slipknot", "Tool", "Sepultura", "Testament", "Exodus", "Kreator", "Lamb of God", "Mastodon", "Opeth",
  ],
};


/** Real artists through the public picker, a sitting per crowd (a sitting may make 20 live searches). */
async function resolveRealCrowds(request: APIRequestContext, token: string): Promise<{ id: string; urn: string }[][]> {
  const crowds: { id: string; urn: string }[][] = [];
  for (const acts of Object.values(REAL_CROWDS)) {
    const view = await (await request.get(`/api/v1/public/survey/${token}`)).json();
    const ids: { id: string; urn: string }[] = [];
    for (const act of acts) {
      const found = await (
        await request.post("/api/v1/public/picker", { data: { token, nonce: view.nonce, q: act, type: "artist" } })
      ).json();
      const top = found.items?.[0];
      if (!top || top.name.normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase() !== act.toLowerCase()) continue;
      const sel = await (await request.post("/api/v1/public/select", { data: { token, nonce: view.nonce, entity_id: top.entity_id } })).json();
      if (sel.eligible) ids.push({ id: top.entity_id, urn: "urn:entity:artist" });
    }
    expect(ids.length).toBeGreaterThanOrEqual(6);
    crowds.push(ids);
  }
  return crowds;
}

test("my people reads a real audience for each group from Qloo, and says what it is", async ({ page, request }, info) => {
  test.setTimeout(420_000);
  await resetRateLimits();
  const problems = watch(page);
  const venue = await publishedVenue(request);

  const crowds = await resolveRealCrowds(request, venue.token);
  await plantRealCrowds(venue.qrId, venue.businessId, crowds, 120, 11);
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

test("soundcheck an act against a real crowd: a score from Qloo's answers, every step open, suggestions built by the worker", async ({ page, request }, info) => {
  test.setTimeout(480_000);
  await resetRateLimits();
  const problems = watch(page);
  const venue = await publishedVenue(request);
  const crowds = await resolveRealCrowds(request, venue.token);
  await plantRealCrowds(venue.qrId, venue.businessId, crowds, 120, 13);
  await sql("UPDATE job SET run_after = now() WHERE business_id = $1", [venue.businessId]);
  await expect
    .poll(async () => (await sql("SELECT count(*)::int AS n FROM tribe_version WHERE business_id = $1 AND state IN ('provisional', 'named')", [venue.businessId])).rows[0]?.n, {
      timeout: 150_000,
      intervals: [3000],
    })
    .toBeGreaterThan(0);

  await signIn(page, venue.email);
  await page.locator(".shell__main").waitFor();
  const menu = page.getByRole("button", { name: "Menu" });
  if (await menu.isVisible()) await menu.click();
  await page.getByRole("navigation", { name: "Pages" }).getByRole("link", { name: "Soundcheck" }).click();
  await expect(page.getByText("Checked against your")).toBeVisible();

  // Suggestions are built by the worker and offered as chips once they are ready.
  await expect(page.getByRole("group", { name: "Suggested acts" })).toBeVisible({ timeout: 150_000 });

  // Search for a real act and check it.
  await page.getByLabel("Search for an act").fill("Ariana Grande");
  const row = page.getByRole("listitem").filter({ hasText: "Ariana Grande" }).first();
  await expect(row).toBeVisible({ timeout: 30_000 });
  await row.getByRole("button", { name: "Soundcheck" }).click();
  const verdict = page.getByTestId("verdict");
  await expect(verdict).toHaveAttribute("data-status", "ok", { timeout: 60_000 });
  const score = Number(await page.getByTestId("score").innerText());
  expect(score).toBeGreaterThan(0);
  expect(score).toBeLessThanOrEqual(100);
  await expect(page.getByTestId("range")).toContainText("This is fit, not a sales forecast");
  await expect(page.locator('[data-testid^="group-"]')).toHaveCount(3);
  await expect(page.getByText("Why it fits")).toBeVisible();
  await expect(page.getByText("Watch out for")).toBeVisible();
  await expect(page.getByTestId("alone")).toContainText("if your whole crowd were one group");

  // Qloo against an AI alone: Qloo's own neighbours of the act, and an honest "no AI answer" while no model key is set.
  const compare = page.getByTestId("compare");
  await expect(compare.getByTestId("compare-summary")).toContainText("Qloo returned", { timeout: 60_000 });
  await expect(compare.locator(".cmp__col").first().locator("li")).toHaveCount(6);
  // with no model key the panel says none is configured; with a key set but a service that cannot be reached (the README's stand-in address) it says it did not answer. Either way it never invents an AI list.
  await expect(compare.getByTestId("ai-unavailable")).toContainText(/no AI service is configured|the AI service did not answer/);

  // Show the working: the formula, the components and the fingerprint are all on the page.
  await page.getByText("Show the working").click();
  await expect(page.getByText(/Score = 100 x group fit/)).toBeVisible();
  await expect(page.getByText("Peer evidence").first()).toBeVisible();
  // The Qloo calls behind it: one per group, each with what was sent.
  await page.getByText("The Qloo calls behind this score").click();
  const calls = page.getByTestId("calls").locator("li");
  await expect(calls).toHaveCount(3);
  await expect(calls.first()).toContainText("/v2/insights");
  await expect(calls.first()).toContainText("acts compared");
  await verdict.scrollIntoViewIfNeeded();
  await verdict.screenshot({ path: `e2e-shots/${info.project.name}-light-soundcheck-verdict.png` });
  expect((await new AxeBuilder({ page }).analyze()).violations).toEqual([]);
  await setTheme(page, "dark");
  await page.waitForTimeout(450);
  await verdict.screenshot({ path: `e2e-shots/${info.project.name}-dark-soundcheck-verdict.png` });
  expect((await new AxeBuilder({ page }).analyze()).violations).toEqual([]);
  await setTheme(page, "light");

  // A suggested act opens its stored verdict at once, with the same score every time it is opened.
  const first = page.getByRole("group", { name: "Suggested acts" }).getByRole("button").first();
  await first.click();
  await expect(page.getByTestId("verdict")).toHaveAttribute("data-status", "ok");
  // "Was this useful?": a yes and a line, sent without anything that says who sent it.
  const note = `Clear and honest ${Date.now()}`;
  await page.getByTestId("verdict").getByTestId("feedback").getByRole("button", { name: "Yes" }).click();
  await page.getByLabel("Anything to add? (optional)").fill(note);
  await page.getByRole("button", { name: "Send", exact: true }).click();
  await expect(page.getByTestId("feedback-thanks")).toBeVisible();
  expect((await sql("SELECT kind, useful FROM feedback WHERE note = $1", [note])).rows).toEqual([{ kind: "soundcheck", useful: true }]);

  // The Booking Brief: the same crowd and acts on one sheet, a real PDF, and a share link that can be turned off.
  await page.goto("/app/brief");
  await expect(page.getByTestId("brief")).toHaveAttribute("data-status", "ok", { timeout: 30_000 });
  await expect(page.getByTestId("brief-act")).toHaveCount(3);
  await expect(page.getByText("How this was computed.")).toBeVisible();
  const pdf = await page.request.get((await page.getByTestId("pdf").getAttribute("href")) as string);
  expect(pdf.headers()["content-type"]).toBe("application/pdf");
  expect((await pdf.body()).subarray(0, 5).toString()).toBe("%PDF-");
  await page.getByTestId("brief").screenshot({ path: `e2e-shots/${info.project.name}-light-brief.png` });
  expect((await new AxeBuilder({ page }).analyze()).violations).toEqual([]);
  await setTheme(page, "dark");
  await page.waitForTimeout(450);
  await page.getByTestId("brief").screenshot({ path: `e2e-shots/${info.project.name}-dark-brief.png` });
  expect((await new AxeBuilder({ page }).analyze()).violations).toEqual([]);
  await setTheme(page, "light");
  await page.getByRole("button", { name: "Create a share link" }).click();
  const url = (await page.getByTestId("share-link").locator(".mono").innerText()).trim();
  expect(url).toMatch(/\/b\/[A-Za-z0-9_-]{30,}$/);
  const names = await page.getByTestId("brief-act").locator("strong").allInnerTexts();
  const sharedPath = new URL(url).pathname;
  const anon = await page.context().browser()!.newContext({ baseURL: new URL(page.url()).origin }); // no account, no cookies
  const shared = await anon.newPage();
  await shared.goto(sharedPath);
  await expect(shared.getByTestId("brief-act")).toHaveCount(3);
  expect(await shared.getByTestId("brief-act").locator("strong").allInnerTexts()).toEqual(names);
  expect((await new AxeBuilder({ page: shared }).analyze()).violations).toEqual([]);
  await page.getByRole("button", { name: "Turn off" }).click();
  await shared.reload();
  await expect(shared.getByText("This brief is no longer available.")).toBeVisible();
  await anon.close();
  expect(problems).toEqual([]);
});

test("grow reads a real crowd: a button press queues the worker, the page waits and then shows what Qloo answered with the checks beside it", async ({ page, request }, info) => {
  test.setTimeout(480_000);
  await resetRateLimits();
  const problems = watch(page);
  const venue = await publishedVenue(request);
  const crowds = await resolveRealCrowds(request, venue.token);
  await plantRealCrowds(venue.qrId, venue.businessId, crowds, 120, 17);
  await sql("UPDATE job SET run_after = now() WHERE business_id = $1", [venue.businessId]);
  await expect
    .poll(async () => (await sql("SELECT count(*)::int AS n FROM tribe_version WHERE business_id = $1 AND state IN ('provisional', 'named')", [venue.businessId])).rows[0]?.n, {
      timeout: 150_000,
      intervals: [3000],
    })
    .toBeGreaterThan(0);

  await signIn(page, venue.email);
  await page.goto("/app/grow");
  await expect(page.getByTestId("not-ready")).toHaveAttribute("data-state", "not_run");
  await page.getByTestId("ask").click();
  await expect(page.getByTestId("not-ready")).toHaveAttribute("data-state", /queued|running/, { timeout: 15_000 });
  await shot(page, info, "live-grow-waiting");
  // the worker runs it against real Qloo and the page updates itself
  await expect(page.getByTestId("ghosts")).toBeVisible({ timeout: 300_000 });
  await expect(page.getByTestId("not-ready")).toHaveCount(0);
  const ghosts = page.getByTestId("ghosts");
  const status = await ghosts.getAttribute("data-status");
  expect(["ok", "none", "not_group_specific"]).toContain(status);
  if (status === "ok") {
    expect(await page.getByTestId("ghost").count()).toBeGreaterThan(0);
    await expect(page.getByTestId("ghost-carrying").first()).toContainText("Fewer than 10 of your guests pick it.");
  }
  for (const id of ["nearby", "elsewhere"]) {
    const section = page.getByTestId(id);
    await expect(section).toHaveAttribute("data-status", /ok|empty/);
    await expect(page.getByTestId(`${id}-note`)).not.toBeEmpty();
    if ((await section.getAttribute("data-status")) === "ok") {
      await expect(section.getByTestId("place").first()).toBeVisible();
      await expect(page.getByTestId(`${id}-check`)).toContainText("of its first ten places");
    }
  }
  await page.getByTestId("calls-disc").locator("summary").click();
  await expect(page.getByTestId("calls").locator("li").first()).toContainText("/v2/insights", { timeout: 15_000 });
  expect(await page.getByTestId("calls").locator("li").count()).toBeGreaterThanOrEqual(5);
  await shot(page, info, "live-grow");
  expect((await new AxeBuilder({ page }).analyze()).violations).toEqual([]);
  await setTheme(page, "dark");
  await shot(page, info, "live-grow", "dark");
  expect((await new AxeBuilder({ page }).analyze()).violations).toEqual([]);
  await setTheme(page, "light");
  expect(problems.filter((p) => !/_rsc=|ERR_ABORTED/.test(p))).toEqual([]);
});
