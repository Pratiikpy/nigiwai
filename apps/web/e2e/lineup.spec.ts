import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page } from "@playwright/test";
import { publishedVenue, resetRateLimits, setTheme, shot, signIn, watch } from "./helpers";

test.beforeEach(async () => resetRateLimits());

async function a11y(page: Page, label: string) {
  const result = await new AxeBuilder({ page }).analyze();
  expect(result.violations.map((v) => `${label}: ${v.id} ${v.nodes.map((n) => n.html.slice(0, 120)).join(" | ")}`)).toEqual([]);
}

async function openPeople(page: Page) {
  await page.locator(".shell__main").waitFor(); // the shell renders once the session has loaded
  const menu = page.getByRole("button", { name: "Menu" });
  if (await menu.isVisible()) await menu.click();
  await page.getByRole("navigation", { name: "Pages" }).getByRole("link", { name: "My people" }).click();
  await expect(page.getByRole("heading", { name: "My people", level: 1 })).toBeVisible();
}

const READY = {
  place: { mbid: "d7cb3789-c62f-4f5c-a0e0-9e1ceb525114", name: "Mercury Lounge", area: "Lower East Side" },
  status: "ready",
  progress: {},
  error: null,
  result: {
    label: "Modelled from public lineups",
    state: "profile",
    reason: "",
    events: { used: 33, with_lineup: 33, first: "1997-09-03", last: "2026-10-23" },
    performers: { unique: 120, resolved: 43, rate: 0.358 },
    top_acts: [
      { name: "Jarv", mbid: "a", entity_id: null, events: 5 },
      { name: "Damn Skippy", mbid: "b", entity_id: "e1", events: 3 },
      { name: "Bon Savants", mbid: "c", entity_id: "e2", events: 2 },
    ],
    top_tags: [
      { tag_id: "t1", name: "Indie Rock", acts: 14, share: 0.33 },
      { tag_id: "t2", name: "Indie Pop", acts: 11, share: 0.26 },
    ],
    top_feel: [{ tag_id: "f1", name: "Atmospheric", acts: 12, share: 0.28 }],
    groups: null,
  },
};

test("public lineups: search, wait, a profile, not enough data, and a failure each read honestly", async ({ page, request }, info) => {
  const problems = watch(page);
  const venue = await publishedVenue(request);
  await signIn(page, venue.email);

  // The API's answers are scripted here so every state of the screen is exercised without waiting on a public service;
  // the real MusicBrainz and Qloo run end to end in live.spec.ts.
  let current: unknown = null;
  await page.route("**/api/v1/tenants/*/businesses/*/lineup", async (route) => {
    const method = route.request().method();
    if (method === "POST") {
      current = { ...READY, status: "running", progress: { events: 33, performers: 120, stage: "resolving" }, result: null };
      return route.fulfill({ status: 202, contentType: "application/json", body: JSON.stringify({ queued: true }) });
    }
    if (method === "DELETE") {
      current = null;
      return route.fulfill({ status: 204 });
    }
    return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(current) });
  });
  await page.route("**/api/v1/tenants/*/businesses/*/lineup/search*", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify([
        { mbid: READY.place.mbid, name: "Mercury Lounge", area: "Lower East Side", address: "217 East Houston St.", kind: "Venue" },
        { mbid: "09afa9f3-d118-4431-802b-5136c37f67fe", name: "Mercury Lounge", area: "Austin", address: null, kind: "venue, Austin, TX" },
      ]),
    }),
  );

  await openPeople(page);
  await expect(page.getByRole("heading", { name: "Start from public lineups" })).toBeVisible();
  await shot(page, info, "lineup-start");
  await a11y(page, "lineup start");

  await page.getByLabel("Venue name").fill("Mercury Lounge");
  await page.getByRole("button", { name: "Search" }).click();
  await expect(page.getByRole("list", { name: "Matching venues" }).getByRole("listitem")).toHaveCount(2);
  await shot(page, info, "lineup-results");
  await a11y(page, "lineup results");

  await page.getByRole("button", { name: "Use this venue" }).first().click();
  await expect(page.getByText(/Reading public lineups for Mercury Lounge: 33 events, 120 acts/)).toBeVisible();
  await shot(page, info, "lineup-working");
  await a11y(page, "lineup working");

  // Ready.
  current = READY;
  await page.reload();
  await expect(page.getByText("Modelled", { exact: false }).first()).toBeVisible();
  await expect(page.getByText("43 of 120 acts matched in Qloo")).toBeVisible();
  await expect(page.getByText("33 events, 1997 to 2026")).toBeVisible();
  await expect(page.getByText("not in Qloo").first()).toBeVisible();
  await expect(page.getByText(/Only exact matches count/)).toBeVisible();
  await expect(page.getByText(/this view is partial/)).toBeVisible();
  await shot(page, info, "lineup-ready");
  await a11y(page, "lineup ready");
  await setTheme(page, "dark");
  await shot(page, info, "lineup-ready", "dark");
  await a11y(page, "lineup ready dark");
  await setTheme(page, "light");

  // Not enough public data.
  current = {
    ...READY,
    result: { ...READY.result, state: "insufficient", reason: "Not enough public data yet: 6 events with a lineup and 18 acts Qloo could match exactly. This needs at least 10 events and 15 acts." },
  };
  await page.reload();
  await expect(page.getByText("Not enough public data yet", { exact: false }).first()).toBeVisible();
  await shot(page, info, "lineup-insufficient");
  await a11y(page, "lineup insufficient");

  // Failed.
  current = { ...READY, status: "failed", result: null, error: "MusicBrainz is not answering right now (busy)" };
  await page.reload();
  await expect(page.getByText("That didn’t work.")).toBeVisible();
  await a11y(page, "lineup failed");

  // Remove and start again.
  await page.getByRole("button", { name: "Remove this and choose another" }).click();
  await expect(page.getByLabel("Venue name")).toBeVisible();
  expect(problems).toEqual([]);
});
