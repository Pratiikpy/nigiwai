import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page } from "@playwright/test";
import { setTheme, shot, signUp, watch } from "./helpers";

async function a11y(page: Page, label: string) {
  const result = await new AxeBuilder({ page }).analyze();
  expect(result.violations.map((v) => `${label}: ${v.id} ${v.nodes.map((n) => n.html.slice(0, 120)).join(" | ")}`)).toEqual([]);
}
const prefetch = /requestfailed: GET \S+[?&]_rsc=\S+ net::ERR_ABORTED/;

test("a mistyped address gets a plain 404 page in the product's own look, with the way back", async ({ page }, info) => {
  const problems = watch(page);
  for (const address of ["/this-page-does-not-exist", "/try/", "/invite/a-path-style-link", "/app/not-a-page-either"]) {
    const response = await page.goto(address);
    if (address === "/try/") continue; // an existing page with a trailing slash: not a 404
    expect(response?.status(), address).toBe(404);
    await expect(page.getByTestId("not-found")).toContainText("We can’t find that page.");
  }
  await page.goto("/this-page-does-not-exist");
  await shot(page, info, "not-found");
  await a11y(page, "404");
  await setTheme(page, "dark");
  await shot(page, info, "not-found", "dark");
  await a11y(page, "404 dark");
  await page.getByRole("link", { name: "Go to the front page" }).click();
  await expect(page).toHaveURL(/\/$/);
  expect(problems.filter((p) => !/404|Failed to load resource/.test(p) && !prefetch.test(p))).toEqual([]);
});

test("a signed-in person who opens an address that is not a page gets the same plain page", async ({ page }, info) => {
  const problems = watch(page);
  await signUp(page, "The Lantern");
  const response = await page.goto("/app/not-a-page-either");
  expect(response?.status()).toBe(404);
  await expect(page.getByTestId("not-found")).toBeVisible();
  await shot(page, info, "not-found-app");
  await a11y(page, "404 in the app");
  await page.getByRole("link", { name: "Go to the front page" }).click();
  await expect(page).toHaveURL(/\/$/);
  expect(problems.filter((p) => !/404|Failed to load resource/.test(p) && !prefetch.test(p))).toEqual([]);
});
