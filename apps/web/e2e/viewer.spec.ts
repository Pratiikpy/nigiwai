import { expect, test } from "@playwright/test";
import { keepRecoveryCode, PASSWORD, plantCrowd, publishedVenue, resetRateLimits, signIn, uniqueEmail, watch } from "./helpers";

test.beforeEach(async () => resetRateLimits());

const PAGES = ["/app", "/app/today", "/app/venue", "/app/survey", "/app/map", "/app/people", "/app/soundcheck", "/app/sound", "/app/grow", "/app/atlas", "/app/moves", "/app/drafts", "/app/ask", "/app/brief", "/app/proof", "/app/posters", "/app/team", "/app/account"];

test("a viewer can open every page of the account and none of them tries to change anything", async ({ page, request, browser }) => {
  test.setTimeout(300_000);
  const venue = await publishedVenue(request);
  await plantCrowd(venue.businessId, venue.qrId, 70);

  // the owner invites a viewer; the viewer joins in their own browser
  await signIn(page, venue.email);
  await page.goto("/app/team");
  await page.getByTestId("team-invite-role").selectOption("viewer");
  await page.getByTestId("team-invite-create").click();
  const link = new URL(await page.getByTestId("team-link").inputValue());
  const context = await browser.newContext({ baseURL: page.url().split("/app")[0], viewport: page.viewportSize() ?? undefined });
  const v = await context.newPage();
  const problems = watch(v);
  const writes: string[] = [];
  const refused: string[] = [];
  v.on("request", (r) => {
    if (r.method() !== "GET" && r.url().includes("/api/v1/tenants/")) writes.push(`${r.method()} ${new URL(r.url()).pathname}`);
  });
  v.on("response", (r) => {
    if (r.url().includes("/api/v1/tenants/") && r.status() >= 400) refused.push(`${r.status()} ${r.request().method()} ${new URL(r.url()).pathname}`);
  });
  await v.goto(`${link.pathname}${link.hash}`);
  await v.getByLabel("Email").fill(uniqueEmail("viewer"));
  await v.getByLabel("Choose a password").fill(PASSWORD);
  await v.getByTestId("invite-submit").click();
  await keepRecoveryCode(v);
  await expect(v).toHaveURL(/\/app$/);
  await expect(v.locator(".side__who")).toContainText("viewer");

  for (const address of PAGES) {
    await v.goto(address);
    await v.waitForLoadState("networkidle");
    await expect(v.getByRole("heading", { level: 1 }).first(), address).toBeVisible();
    // no banner says something failed or was refused
    await expect(v.locator('.banner[data-tone="error"]'), address).toHaveCount(0);
  }
  expect(writes, "a viewer's pages must not send a change").toEqual([]);
  expect(refused, "a viewer's pages must not run into a refusal").toEqual([]);
  // the invitation page asks who is signed in before it shows the form, and the answer for a stranger is the 401 the browser logs
  expect(problems.filter((p) => !/_rsc=.*ERR_ABORTED|openfreemap|webgl|GPU|status of 401.*\/auth\/me/i.test(p))).toEqual([]);
  await context.close();
});
