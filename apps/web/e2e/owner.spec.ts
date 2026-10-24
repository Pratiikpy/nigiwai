import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page } from "@playwright/test";
import { resetRateLimits, setTheme, shot, signUp, watch } from "./helpers";

test.beforeEach(async () => resetRateLimits());

/** On a phone the navigation lives in a drawer behind the Menu button. */
async function nav(page: Page, name: string) {
  await page.locator(".shell__main").waitFor(); // the shell renders once the session has loaded
  const menu = page.getByRole("button", { name: "Menu" });
  if (await menu.isVisible()) await menu.click();
  await page.getByRole("navigation", { name: "Pages" }).getByRole("link", { name }).click();
}

test("an owner sets up a venue, publishes a survey and prints a poster", async ({ page }, info) => {
  const problems = watch(page);
  await signUp(page, "The Lantern");

  // Overview: nothing is done yet.
  await expect(page.getByRole("heading", { name: "The Lantern", level: 1 })).toBeVisible();
  const steps = page.getByRole("list", { name: "Set-up steps" }).getByRole("listitem");
  await expect(steps).toHaveCount(3);
  // the layout, not only the count: one number per step and a text column wide enough to read (a rule from another page once
  // squeezed these to a word a line and drew a second number, and nothing here noticed)
  const laid = await steps.evaluateAll((els) =>
    els.map((el) => ({ text: (el.querySelector(".ov-steps__t") as HTMLElement).getBoundingClientRect().width, before: getComputedStyle(el, "::before").content })),
  );
  for (const step of laid) {
    expect(step.before).toBe("none");
    expect(step.text).toBeGreaterThan(140);
  }
  await shot(page, info, "overview-empty");
  expect((await new AxeBuilder({ page }).analyze()).violations).toEqual([]);

  // Venue
  await page.getByRole("link", { name: "Start" }).click();
  await expect(page.getByRole("heading", { name: "Your venue", level: 1 })).toBeVisible();
  await page.getByLabel("Name", { exact: true }).fill("The Lantern");
  await page.getByLabel("Type").selectOption("live_music_venue");
  await page.getByLabel("Currency").fill("gbp");
  await page.getByLabel("Latitude").fill("51.5072");
  await page.getByLabel("Longitude").fill("-0.1276");
  await page.getByLabel("Time zone").fill("Europe/London");
  await page.getByRole("button", { name: "Fri" }).click();
  await page.getByRole("button", { name: "Sat" }).click();
  await shot(page, info, "venue-filled");
  await page.getByRole("button", { name: "Save", exact: true }).click();
  await expect(page.getByText("Saved.")).toBeVisible();
  expect((await new AxeBuilder({ page }).analyze()).violations).toEqual([]);

  // Survey
  await nav(page, "Survey");
  await expect(page.getByRole("heading", { name: "Survey", level: 1 })).toBeVisible();
  await page.getByLabel("What guests get").fill("A free coffee");
  await page.getByLabel("How to claim it").fill("Show this screen at the bar.");
  await shot(page, info, "survey-editor");
  await page.getByRole("button", { name: "Publish" }).click();
  await expect(page.getByText(/Published as version 1/)).toBeVisible();
  expect((await new AxeBuilder({ page }).analyze()).violations).toEqual([]);

  // Posters
  await nav(page, "QR posters");
  await page.getByLabel("Where will it go?").fill("Bar end");
  await page.getByRole("button", { name: "Create code" }).click();
  await expect(page.getByRole("heading", { name: "Bar end" })).toBeVisible();
  await expect(page.getByRole("img", { name: "QR code for Bar end" })).toBeVisible();
  await shot(page, info, "posters");
  const poster = await page.getByRole("link", { name: "A4 poster" }).getAttribute("href");
  const pdf = await page.request.get(poster as string);
  expect(pdf.status()).toBe(200);
  expect(pdf.headers()["content-type"]).toBe("application/pdf");
  expect((await pdf.body()).subarray(0, 4).toString()).toBe("%PDF");
  expect((await new AxeBuilder({ page }).analyze()).violations).toEqual([]);

  // Back to the overview: all three steps done.
  await nav(page, "Overview");
  await expect(page.locator(".ov-steps li[data-done='true']")).toHaveCount(3);
  await shot(page, info, "overview-done");

  await setTheme(page, "dark");
  await shot(page, info, "overview-done", "dark");
  expect((await new AxeBuilder({ page }).analyze()).violations).toEqual([]);

  expect(problems).toEqual([]);
});
