import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page } from "@playwright/test";
import { randomUUID } from "node:crypto";
import { resetRateLimits, setTheme, shot, sql, watch } from "./helpers";

test.beforeEach(async () => resetRateLimits());

async function a11y(page: Page, label: string) {
  const result = await new AxeBuilder({ page }).analyze();
  expect(result.violations.map((v) => `${label}: ${v.id} ${v.nodes.map((n) => n.html.slice(0, 120)).join(" | ")}`)).toEqual([]);
}

test("evidence: every research test is listed with how it was run and what it does not show, wins and losses alike", async ({ page }, info) => {
  const problems = watch(page);
  await page.goto("/evidence");
  await expect(page.getByRole("heading", { name: /What we tested, including what Qloo lost/, level: 1 })).toBeVisible();
  await expect(page.getByTestId("proof")).toHaveCount(15);
  // the tally is counted from the list, and the list contains losses as plainly as wins
  const tally = (await page.getByTestId("tally").innerText()).replace(/\s+/g, " ");
  expect(tally).toMatch(/5 Won 4 Tied 5 Lost 1 Open/);
  await expect(page.getByTestId("proof").filter({ hasText: "Lost" }).first()).toBeVisible();
  for (const p of await page.getByTestId("proof").all()) await expect(p).toContainText("Limits.");
  // nothing shaped like a Qloo response: no entity ids, no urns, no affinity fields
  const body = await page.locator("main").innerText();
  expect(body).not.toMatch(/urn:(entity|tag)|entity_id|[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}|"affinity"/i);
  await shot(page, info, "evidence");
  await a11y(page, "evidence");
  await setTheme(page, "dark");
  await shot(page, info, "evidence", "dark");
  await a11y(page, "evidence dark");
  expect(problems).toEqual([]);
});

test("privacy: what is stored, what is never collected, and the rules; the waitlist is described apart from the survey", async ({ page }, info) => {
  const problems = watch(page);
  await page.goto("/privacy");
  await expect(page.getByRole("heading", { name: /A person is never singled out/, level: 1 })).toBeVisible();
  await expect(page.getByTestId("stored").getByRole("listitem")).toHaveCount(10);
  await expect(page.getByTestId("never")).toContainText("The phone's location, or the guest's IP address");
  await expect(page.getByText("Groups under 10 people are never shown to an owner.")).toBeVisible();
  await expect(page.getByText("Separate from the guest survey: the owner waitlist")).toBeVisible();
  await shot(page, info, "privacy");
  await a11y(page, "privacy");
  await setTheme(page, "dark");
  await a11y(page, "privacy dark");
  expect(problems).toEqual([]);
});

test("business case: the waitlist asks for consent, answers a repeat like a first sign-up, and ignores a script", async ({ page }, info) => {
  const problems = watch(page);
  const email = `waitlist-${randomUUID().slice(0, 8)}@example.com`;
  await page.goto("/business");
  await expect(page.getByRole("heading", { name: /One question, answered for every room/, level: 1 })).toBeVisible();
  await expect(page.getByText("The price is a hypothesis we have not tested")).toBeVisible();
  await shot(page, info, "business");
  await a11y(page, "business");

  const field = page.getByLabel("Work email");
  const join = page.getByRole("button", { name: "Join the waitlist" });
  await expect(join).toBeEnabled();
  // no consent: refused with a reason, nothing stored
  await field.fill(email);
  await join.click();
  await expect(page.getByText("Please agree to the note above to join the waitlist.")).toBeVisible();
  // a bad address: refused
  await page.getByRole("checkbox").check();
  await field.fill("not an email");
  await join.click();
  await expect(page.getByText("That doesn't look like an email address.")).toBeVisible();
  expect((await sql("SELECT count(*)::int AS n FROM waitlist WHERE email_key = $1", [email])).rows[0]?.n).toBe(0);
  // a person cannot reach the hidden field by keyboard
  await expect(page.locator("#wl-website")).toHaveAttribute("tabindex", "-1");

  await field.fill(email);
  await join.click();
  await expect(page.getByText("You’re on the list.")).toBeVisible();
  expect((await sql("SELECT consent_version FROM waitlist WHERE email_key = $1", [email])).rows).toEqual([{ consent_version: "waitlist-v1" }]);
  // the same address again says the same thing and stores nothing new
  await page.goto("/business");
  await page.getByLabel("Work email").fill(email.toUpperCase());
  await page.getByRole("checkbox").check();
  await page.getByRole("button", { name: "Join the waitlist" }).click();
  await expect(page.getByText("You’re on the list.")).toBeVisible();
  expect((await sql("SELECT count(*)::int AS n FROM waitlist WHERE email_key = $1", [email.toLowerCase()])).rows[0]?.n).toBe(1);
  await shot(page, info, "business-joined");
  await a11y(page, "business joined");
  await setTheme(page, "dark");
  await a11y(page, "business dark");
  expect(problems.filter((p) => !p.includes("422"))).toEqual([]);
});
