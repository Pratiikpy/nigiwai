import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page } from "@playwright/test";
import { plantArtist, plantLineup, publishedVenue, resetRateLimits, setTheme, shot, signIn, sql, watch } from "./helpers";

test.beforeEach(async () => resetRateLimits());

async function openSoundcheck(page: Page) {
  await page.locator(".shell__main").waitFor(); // the shell renders once the session has loaded
  const menu = page.getByRole("button", { name: "Menu" });
  if (await menu.isVisible()) await menu.click();
  await page.getByRole("navigation", { name: "Pages" }).getByRole("link", { name: "Soundcheck" }).click();
  await expect(page.getByRole("heading", { name: "Soundcheck", level: 1 })).toBeVisible();
}

async function a11y(page: Page, label: string) {
  const result = await new AxeBuilder({ page }).analyze();
  expect(result.violations.map((v) => `${label}: ${v.id} ${v.nodes.map((n) => n.html.slice(0, 120)).join(" | ")}`)).toEqual([]);
}

async function search(page: Page, name: string) {
  await page.getByLabel("Search for an act").fill(name);
  const row = page.getByRole("listitem").filter({ hasText: name }).first();
  await expect(row).toBeVisible({ timeout: 20_000 });
  await row.getByRole("button", { name: "Soundcheck" }).click();
}

test("soundcheck: no crowd, a lineup too thin for a number, and an act that fails the venue's limits", async ({ page, request }, info) => {
  test.setTimeout(180_000);
  const problems = watch(page);
  const venue = await publishedVenue(request);
  await signIn(page, venue.email);
  await openSoundcheck(page);

  // Nothing to check against yet: it says what to do and offers no search.
  await expect(page.getByText("There is no crowd to check against yet.")).toBeVisible();
  await expect(page.getByLabel("Search for an act")).toHaveCount(0);
  await shot(page, info, "soundcheck-no-crowd");
  await a11y(page, "soundcheck no crowd");

  // A public lineup with 6 events: the crowd exists, the number does not.
  await plantLineup(venue.tenantId, venue.businessId, { events: 6 });
  const thin = await plantArtist(`Newcomer ${venue.businessId.slice(0, 6)}`, ["Folk"]);
  await page.reload();
  await expect(page.getByText("Modelled from public lineups.")).toBeVisible();
  await search(page, `Newcomer ${venue.businessId.slice(0, 6)}`);
  await expect(page.getByTestId("verdict")).toHaveAttribute("data-status", "insufficient");
  await expect(page.getByTestId("withheld")).toContainText("6 events");
  await expect(page.getByTestId("withheld")).toContainText("at least 10 events");
  await expect(page.getByTestId("score")).toHaveCount(0); // insufficient data shows no number
  await shot(page, info, "soundcheck-thin");
  await a11y(page, "soundcheck thin");
  expect(thin).toBeTruthy();

  // Enough lineup, but the act's genre is on the owner's excluded list: no Qloo call, no score, a reason.
  await sql("UPDATE lineup_profile SET result = jsonb_set(result, '{events,with_lineup}', '40') WHERE business_id = $1", [venue.businessId]);
  await sql("UPDATE location SET excluded_genres = ARRAY['death metal'], capacity = 120, curfew = '23:00' WHERE business_id = $1", [venue.businessId]);
  const bad = `Grave Choir ${venue.businessId.slice(0, 6)}`;
  await plantArtist(bad, ["Death Metal"]);
  await page.reload();
  await search(page, bad);
  await expect(page.getByTestId("verdict")).toHaveAttribute("data-status", "fails_constraint");
  await expect(page.getByTestId("withheld")).toContainText("Death Metal is on your excluded list");
  await expect(page.getByTestId("constraints")).toContainText("Capacity");
  await expect(page.getByTestId("constraints")).toContainText("not scored");
  await shot(page, info, "soundcheck-fails");
  await a11y(page, "soundcheck fails");
  await setTheme(page, "dark");
  await shot(page, info, "soundcheck-fails", "dark");
  await a11y(page, "soundcheck fails dark");
  expect(problems).toEqual([]);
});

test("booking brief: with no crowd it says there is not enough data and offers nothing to share", async ({ page, request }, info) => {
  const problems = watch(page);
  const venue = await publishedVenue(request);
  await signIn(page, venue.email);
  await page.locator(".shell__main").waitFor();
  const menu = page.getByRole("button", { name: "Menu" });
  if (await menu.isVisible()) await menu.click();
  await page.getByRole("navigation", { name: "Pages" }).getByRole("link", { name: "Booking Brief" }).click();
  await expect(page.getByRole("heading", { name: "Booking Brief", level: 1 })).toBeVisible();
  await expect(page.getByTestId("brief")).toHaveAttribute("data-status", "thin");
  await expect(page.getByRole("heading", { name: "Not enough data yet" })).toBeVisible();
  await expect(page.getByText(/There is no crowd yet/)).toBeVisible();
  await expect(page.getByRole("button", { name: "Create a share link" })).toBeDisabled();
  // The PDF is still a real one-page file that says the same thing.
  const pdf = await page.request.get(await page.getByTestId("pdf").getAttribute("href") as string);
  expect(pdf.headers()["content-type"]).toBe("application/pdf");
  expect((await pdf.body()).subarray(0, 5).toString()).toBe("%PDF-");
  await shot(page, info, "brief-thin");
  await new AxeBuilder({ page }).analyze().then((r) => expect(r.violations).toEqual([]));
  await setTheme(page, "dark");
  await shot(page, info, "brief-thin", "dark");
  await new AxeBuilder({ page }).analyze().then((r) => expect(r.violations).toEqual([]));
  // A link that was never made, or has gone, says one plain thing.
  await page.goto("/b/" + "x".repeat(32));
  await expect(page.getByText("This brief is no longer available.")).toBeVisible();
  expect(problems.filter((p) => !p.includes("404"))).toEqual([]);
});

