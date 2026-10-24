import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page } from "@playwright/test";
import { plantCrowd, publishedVenue, resetRateLimits, setTheme, shot, signIn, sql, watch } from "./helpers";

test.beforeEach(async () => resetRateLimits());

async function openPeople(page: Page) {
  await page.locator(".shell__main").waitFor(); // the shell renders once the session has loaded
  const menu = page.getByRole("button", { name: "Menu" });
  if (await menu.isVisible()) await menu.click();
  await page.getByRole("navigation", { name: "Pages" }).getByRole("link", { name: "My people" }).click();
  await expect(page.getByRole("heading", { name: "My people", level: 1 })).toBeVisible();
}

async function a11y(page: Page, label: string) {
  const result = await new AxeBuilder({ page }).analyze();
  expect(result.violations.map((v) => `${label}: ${v.id} ${v.nodes.map((n) => n.html.slice(0, 120)).join(" | ")}`)).toEqual([]);
}

test("my people: empty, thin, forming and named crowds each say the truth", async ({ page, request }, info) => {
  test.setTimeout(240_000);
  const problems = watch(page);
  const venue = await publishedVenue(request);
  await signIn(page, venue.email);
  await openPeople(page);

  // No answers yet.
  await expect(page.getByRole("heading", { name: "No answers yet" })).toBeVisible();
  await shot(page, info, "people-empty");
  await a11y(page, "people empty");

  // A thin crowd: the product says how far it is from groups and shows none.
  await plantCrowd(venue.businessId, venue.qrId, 25, 3);
  await sql("UPDATE job SET run_after = now() WHERE business_id = $1", [venue.businessId]);
  await page.reload();
  await expect(page.getByRole("heading", { name: "Not enough data yet" })).toBeVisible({ timeout: 40_000 });
  await expect(page.getByText("25 of 60")).toBeVisible();
  await expect(page.locator(".tribe-card")).toHaveCount(0);
  await shot(page, info, "people-thin");
  await a11y(page, "people thin");

  // A forming crowd: three provisional groups, unnamed, with real tags and items.
  await plantCrowd(venue.businessId, venue.qrId, 70, 4);
  await sql("UPDATE job SET run_after = now() WHERE business_id = $1", [venue.businessId]);
  await page.reload();
  await expect(page.getByRole("heading", { name: "Forming groups" }).first()).toBeVisible({ timeout: 90_000 });
  await expect(page.locator(".tribe-card")).toHaveCount(3);
  await expect(page.getByText("Provisional").first()).toBeVisible();
  await expect(page.getByText(/Group A/)).toBeVisible();
  // Each group says who it tends to be, or why it cannot (the planted items are not real Qloo entities).
  await expect(page.getByTestId(/^audience-/)).toHaveCount(3);
  await expect(page.getByText("Who they tend to be")).toHaveCount(3);
  // The sample size and how well the group repeats are on every card (PRD M4 acceptance).
  await expect(page.getByTestId(/^reproducibility-/)).toHaveCount(3);
  await expect(page.getByTestId("reproducibility-0")).toContainText(/Tested on a crowd of \d+/);
  await expect(page.getByTestId("reproducibility-0")).toContainText(/overlap \d+%/);
  await shot(page, info, "people-provisional");
  await a11y(page, "people provisional");

  // How it was computed is there, and says what the groups were compared against.
  await page.getByText("How this was computed").click();
  await expect(page.getByText("Same crowd with its tags shuffled")).toBeVisible();
  await expect(page.getByText("Same number of random popular picks")).toBeVisible();
  await shot(page, info, "people-how");

  // A named crowd.
  await plantCrowd(venue.businessId, venue.qrId, 130, 5);
  await sql("UPDATE job SET run_after = now() WHERE business_id = $1", [venue.businessId]);
  await page.reload();
  await expect(page.getByRole("heading", { name: "Named groups" })).toBeVisible({ timeout: 90_000 });
  await expect(page.locator(".tribe-card .pill")).toHaveCount(0);
  await expect(page.locator(".tribe-card h2.tribe").first()).toContainText("crowd");
  await shot(page, info, "people-named");
  await a11y(page, "people named");
  await setTheme(page, "dark");
  await shot(page, info, "people-named", "dark");
  await a11y(page, "people named dark");

  // Proof: nothing shown is invented, and the page says so with the numbers behind it.
  await setTheme(page, "light");
  await page.locator(".shell__main").waitFor(); // the shell renders once the session has loaded
  const menu = page.getByRole("button", { name: "Menu" });
  if (await menu.isVisible()) await menu.click();
  await page.getByRole("navigation", { name: "Pages" }).getByRole("link", { name: "Proof" }).click();
  await expect(page.getByRole("heading", { name: "Proof", level: 1 })).toBeVisible();
  await expect(page.getByTestId("invented-count")).toContainText("0 of");
  await expect(page.getByTestId("invented-count")).not.toContainText("0 of 0");
  await expect(page.getByText(/entities Qloo returned/)).toBeVisible();
  await shot(page, info, "proof");
  await a11y(page, "proof");

  expect(problems).toEqual([]);
});
