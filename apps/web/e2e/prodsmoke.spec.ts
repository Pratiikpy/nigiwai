import { expect, test } from "@playwright/test";
import { PASSWORD, publishedVenue, signIn, watch } from "./helpers";

// A stranger's pass over a deployed copy, through its public address only: no database access, so it runs against any host.
// NIGIWAI_PROD_SMOKE=1 NIGIWAI_WEB_URL=https://... npx playwright test -c playwright.prod.config.ts
// It spends a few live Qloo calls (one verdict, three picker searches) and leaves nothing behind: the account it makes is deleted.
test.skip(process.env.NIGIWAI_PROD_SMOKE !== "1", "set NIGIWAI_PROD_SMOKE=1 to run against a deployed copy");

const tolerated = /openfreemap|ERR_FAILED|Failed to load resource|webgl|GPU/i; // map tiles come from a third party
const prefetch = /requestfailed: GET \S+[?&]_rsc=\S+ net::ERR_ABORTED/;

test("the public pages open, say what they are and log no console errors", async ({ page }) => {
  const problems = watch(page);
  for (const [path, heading] of [
    ["/", /Soundcheck any act on your crowd before you book it/],
    ["/try", /Try a venue/],
    ["/evidence", /./],
    ["/privacy", /./],
    ["/business", /./],
    ["/login", /./],
    ["/signup", /./],
  ] as const) {
    const res = await page.goto(path);
    expect(res?.status(), path).toBe(200);
    await expect(page.getByRole("heading", { level: 1 }).first()).toHaveText(heading);
  }
  expect(problems.filter((p) => !prefetch.test(p) && !tolerated.test(p))).toEqual([]);
});

test("a demo venue opens from stored results and a suggested act gets a verdict with its Qloo calls", async ({ page }) => {
  test.setTimeout(120_000);
  const problems = watch(page);
  const res = await page.request.get("/api/v1/public/demo");
  expect(res.ok()).toBe(true);
  const venues = (await res.json()) as { slug: string; name: string }[];
  expect(venues.length).toBeGreaterThanOrEqual(3);
  await page.goto("/try");
  await page.getByTestId("venue-card").filter({ hasText: venues[0]!.name }).click();
  const chips = page.getByRole("group", { name: "Suggested acts" }).getByRole("button");
  await expect(chips.first()).toBeVisible({ timeout: 15_000 });
  await chips.first().click();
  await expect(page.getByText("The Qloo calls behind this score")).toBeVisible({ timeout: 90_000 });
  expect(problems.filter((p) => !prefetch.test(p) && !tolerated.test(p))).toEqual([]);
});

test("an owner signs up, publishes a survey, a guest answers it on a phone, the owner reads it, then deletes the account", async ({
  page,
  request,
  browser,
}) => {
  test.setTimeout(240_000);
  const venue = await publishedVenue(request, { reward: { title: "A free coffee", detail: "Show this screen at the bar." } });

  // the guest, in their own context
  const guestCtx = await browser.newContext({ viewport: { width: 412, height: 915 }, isMobile: true, hasTouch: true });
  const guest = await guestCtx.newPage();
  const guestProblems = watch(guest);
  await guest.goto(`/s/${venue.token}`);
  await expect(guest.getByRole("heading", { name: /Tell us what you love/, level: 1 })).toBeVisible();
  await guest.getByRole("button", { name: "Start" }).click();
  for (const name of ["Radiohead", "Portishead", "Massive Attack"]) {
    await guest.getByLabel("Search", { exact: true }).fill(name);
    await guest.getByRole("button", { name: new RegExp(`^Add ${name}`) }).first().click({ timeout: 30_000 });
  }
  await expect(guest.getByText("3 of 5 picked")).toBeVisible();
  await guest.getByRole("button", { name: "Continue" }).click();
  await guest.getByRole("button", { name: "Send my picks" }).click();
  await expect(guest.getByText("Your picks are in.")).toBeVisible({ timeout: 30_000 });
  await expect(guest.getByText("If you love these, you might also like")).toBeVisible({ timeout: 30_000 }); // a live Qloo answer
  expect(guestProblems.filter((p) => !prefetch.test(p) && !tolerated.test(p))).toEqual([]);
  await guestCtx.close();

  // the owner reads what came in, through the real sign-in
  const owner = await browser.newContext();
  const op = await owner.newPage();
  const ownerProblems = watch(op);
  await signIn(op, venue.email);
  await expect(op.getByRole("heading", { level: 1 }).first()).toBeVisible();
  for (const [path, heading] of [
    ["/app/survey", "Survey"],
    ["/app/posters", "QR posters"],
    ["/app/today", "Today"],
    ["/app/brief", "Booking Briefs"],
  ] as const) {
    await op.goto(path);
    await expect(op.getByRole("heading", { level: 1 }).first()).toContainText(heading.split(" ")[0]!);
  }
  await op.goto("/app");
  await expect(op.getByText("1", { exact: true }).first()).toBeVisible();

  // and removes everything it made
  await op.goto("/app/account");
  const del = op.getByTestId("delete-account");
  await del.locator("summary").click();
  await del.getByTestId("delete-name").fill("The Lantern");
  await del.getByLabel("Your password").fill(PASSWORD);
  await del.getByTestId("delete-account-go").click();
  await expect(op.getByTestId("no-account")).toBeVisible({ timeout: 30_000 });
  await op.getByTestId("delete-login").locator("summary").click();
  await op.getByTestId("delete-login").getByLabel("Your password").fill(PASSWORD);
  await op.getByTestId("delete-login-go").click();
  await expect(op).toHaveURL(/\/login/, { timeout: 30_000 });
  expect(ownerProblems.filter((p) => !prefetch.test(p) && !tolerated.test(p))).toEqual([]);
  await owner.close();
});
