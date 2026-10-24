import { expect, test } from "@playwright/test";
import { PASSWORD, publishedVenue, resetRateLimits, shot, signIn, sql, watch } from "./helpers";

test.beforeEach(async () => resetRateLimits());
const prefetch = /requestfailed: GET \S+[?&]_rsc=\S+ net::ERR_ABORTED/;
const refused = /Failed to load resource: the server responded with a status of 401/;

test("session: when it ends mid-work the owner is sent to sign in and brought back to the same page", async ({ page, request }, info) => {
  test.setTimeout(120_000);
  const problems = watch(page);
  // a venue with a business, so that its pages have something to load: a page with nothing to fetch could not notice the session had ended
  const { email } = await publishedVenue(request);
  await signIn(page, email);
  await page.goto("/app/today");
  await expect(page.getByRole("heading", { name: "Today", level: 1 })).toBeVisible();

  // the session ends (it expired, or the person signed out on another device)
  await sql("UPDATE app_session SET expires_at = now() - interval '1 minute' WHERE user_id = (SELECT id FROM app_user WHERE email = $1)", [email]);
  await page.goto("/app/moves");
  await expect(page).toHaveURL(/\/login\?next=%2Fapp%2Fmoves$/);
  await expect(page.getByRole("heading", { name: "Welcome back" })).toBeVisible();
  await shot(page, info, "session-ended");

  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password", { exact: true }).fill(PASSWORD);
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page).toHaveURL(/\/app\/moves$/);
  await expect(page.getByRole("heading", { name: "Moves", level: 1 })).toBeVisible();

  // ending it while a page is open and the person acts: a click inside the app, not a reload
  await sql("DELETE FROM app_session WHERE user_id = (SELECT id FROM app_user WHERE email = $1)", [email]);
  await page.locator("main.shell__main").waitFor();
  const menu = page.getByRole("button", { name: "Menu" });
  if (await menu.isVisible()) await menu.click(); // on a phone the side menu is closed until asked for
  await page.getByRole("navigation", { name: "Pages" }).getByRole("link", { name: "Drafts" }).click();
  await expect(page).toHaveURL(/\/login\?next=%2Fapp%2Fdrafts$/);
  expect(problems.filter((p) => !prefetch.test(p) && !refused.test(p))).toEqual([]);
});

test("session: the address to return to is only ever one of our own owner pages", async ({ page, request }) => {
  test.setTimeout(120_000);
  const { email } = await publishedVenue(request);
  for (const next of ["https://evil.example/app", "//evil.example", "/login", "/app/../x", "javascript:alert(1)", "/appx"]) {
    await page.context().clearCookies();
    await page.goto(`/login?next=${encodeURIComponent(next)}`);
    await page.getByLabel("Email").fill(email);
    await page.getByLabel("Password", { exact: true }).fill(PASSWORD);
    await page.getByRole("button", { name: "Sign in" }).click();
    await expect(page, next).toHaveURL(/\/app$/);
  }
  await page.context().clearCookies();
  await page.goto(`/login?next=${encodeURIComponent("/app/team")}`);
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password", { exact: true }).fill(PASSWORD);
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page).toHaveURL(/\/app\/team$/);
});
