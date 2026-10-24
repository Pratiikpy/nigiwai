import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page } from "@playwright/test";
import { publishedVenue, resetRateLimits, seedEntities, setTheme, shot, signIn, sql, watch } from "./helpers";

const tag = `are${Date.now().toString(36)}`;
const prefetch = /requestfailed: GET \S+[?&]_rsc=\S+ net::ERR_ABORTED/;

async function a11y(page: Page, label: string) {
  const result = await new AxeBuilder({ page }).analyze();
  expect(result.violations.map((v) => `${label}: ${v.id} ${v.nodes.map((n) => n.html.slice(0, 120)).join(" | ")}`)).toEqual([]);
}

test.beforeEach(async () => resetRateLimits());

test("areas: an owner lists the areas, a guest taps one instead of typing, and only a listed area is stored", async ({ page, request, browser }, info) => {
  test.setTimeout(240_000);
  const problems = watch(page);
  const venue = await publishedVenue(request);
  await seedEntities(
    tag,
    ["Alder", "Birch", "Cedar"].map((n) => ({ name: n, type: "artist" })),
  );

  // the owner's editor: a list is checked as it is typed, and saved with the survey
  await signIn(page, venue.email);
  await page.goto("/app/survey");
  const areas = page.getByTestId("areas");
  await expect(areas).toBeVisible();
  await expect(page.locator("#s-areas-hint")).toContainText("Leave it empty and guests type their own neighbourhood");
  await areas.fill("Eastside, eastside");
  await expect(page.locator("#s-areas-hint")).toContainText("listed twice");
  await expect(page.getByRole("button", { name: "Publish" })).toBeDisabled();
  await areas.fill("Eastside, me@example.com");
  await expect(page.locator("#s-areas-hint")).toContainText("Just the name of your area");
  await areas.fill("Eastside, Old Town, Riverside");
  await expect(page.locator("#s-areas-hint")).toContainText("Guests pick one of 3");
  await shot(page, info, "areas-editor");
  await a11y(page, "areas editor");
  await setTheme(page, "dark");
  await shot(page, info, "areas-editor", "dark");
  await a11y(page, "areas editor dark");
  await setTheme(page, "light");
  await page.getByRole("button", { name: "Publish" }).click();
  await expect(page.getByText(/Published as version/)).toBeVisible();
  await page.reload();
  await expect(page.getByTestId("areas")).toHaveValue("Eastside, Old Town, Riverside"); // it was kept

  // the guest, in their own browser: tap, not type
  const context = await browser.newContext({ baseURL: page.url().split("/app")[0], viewport: page.viewportSize() ?? undefined });
  const g = await context.newPage();
  const guestProblems = watch(g);
  await g.goto(`/s/${venue.token}`);
  await g.getByRole("button", { name: "Start" }).click();
  for (const name of ["Alder", "Birch", "Cedar"]) {
    await g.getByLabel("Search", { exact: true }).fill(`${name} ${tag}`);
    await g.getByRole("button", { name: `Add ${name} ${tag}` }).click();
  }
  await g.getByRole("button", { name: "Continue" }).click();
  await expect(g.getByRole("heading", { name: "A little about you" })).toBeVisible();
  await expect(g.getByLabel("Where do you usually spend your day?")).toHaveCount(0); // no free text
  const choices = g.getByTestId("district-choices");
  await expect(choices.getByRole("button")).toHaveCount(3);
  await expect(choices.getByRole("button", { name: "Old Town" })).toHaveAttribute("aria-pressed", "false");
  await choices.getByRole("button", { name: "Old Town" }).click();
  await expect(choices.getByRole("button", { name: "Old Town" })).toHaveAttribute("aria-pressed", "true");
  await expect(g.getByText("area Old Town")).toBeVisible(); // the send list says what will be sent
  await shot(g, info, "areas-guest");
  await a11y(g, "areas guest");
  await setTheme(g, "dark");
  await shot(g, info, "areas-guest", "dark");
  await a11y(g, "areas guest dark");
  await setTheme(g, "light");
  // tap again to clear, then choose again
  await choices.getByRole("button", { name: "Old Town" }).click();
  await expect(choices.getByRole("button", { name: "Old Town" })).toHaveAttribute("aria-pressed", "false");
  await choices.getByRole("button", { name: "Riverside" }).click();
  await g.getByRole("button", { name: "Send my picks" }).click();
  await expect(g.getByRole("heading", { level: 1 })).toContainText("still forming");

  const stored = await sql<{ district: string | null }>("SELECT district FROM response WHERE qr_point_id = $1", [venue.qrId]);
  expect(stored.rows).toEqual([{ district: "Riverside" }]);
  expect(problems.filter((p) => !prefetch.test(p))).toEqual([]);
  expect(guestProblems.filter((p) => !prefetch.test(p) && !/Failed to load resource/.test(p))).toEqual([]);
  await context.close();
});
