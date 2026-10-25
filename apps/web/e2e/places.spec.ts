import { randomUUID } from "node:crypto";
import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page } from "@playwright/test";
import { publishedVenue, resetRateLimits, seedEntities, setTheme, shot, signIn, sql, watch } from "./helpers";

// Favourite places in the guest survey (PRD M3). A place is searched near the venue and always live, so the one thing scripted here
// is the answer of that search (Qloo is not asked in these specs); choosing, refusing, sending, storing and the card are the real API
// reading real rows. The real search against the real Qloo runs in live.spec.ts.
const tag = `pl${Date.now().toString(36)}`;
const LANTERN_ROW = { lat: 51.5, lon: -0.12 }; // where publishedVenue puts the room

async function a11y(page: Page, label: string) {
  const result = await new AxeBuilder({ page }).analyze();
  expect(result.violations.map((v) => `${label}: ${v.id} (${v.nodes.length}) ${v.nodes.map((n) => n.html.slice(0, 160)).join(" | ")}`)).toEqual([]);
}

/** A place as the saved index holds one after a search found it: its kind, a taste tag or two, and the facilities Qloo also lists. */
async function plantPlace(name: string, kind: string, extra: [string, string, string][] = []): Promise<{ id: string; name: string }> {
  const id = randomUUID();
  const slug = kind.toLowerCase().replace(/ /g, "_");
  const tags = [
    [`urn:tag:category:place:${slug}`, kind, "urn:tag:category:place"],
    ["urn:tag:ambience:qloo:lively", "Lively", "urn:tag:ambience:qloo"],
    ["urn:tag:payments:place:visa", "Visa", "urn:tag:payments:place"],
    ...extra,
  ];
  await sql("INSERT INTO qloo_entity (entity_id, type, types, name_nfc, tags) VALUES ($1, 'urn:entity:place', ARRAY['urn:entity:place'], $2, $3::jsonb)", [id, name, JSON.stringify(tags)]);
  return { id, name };
}

const row = (p: { id: string; name: string }, address: string) => ({ entity_id: p.id, name: p.name, type: "place", year: null, description: address, disambiguation: null });

test.describe("favourite places", () => {
  test.beforeEach(async () => resetRateLimits());

  test("a guest names favourite places near the room, picks them with an act, sends, and a place that stands for a belief is refused", async ({ page, request }, info) => {
    test.setTimeout(120_000);
    const problems = watch(page);
    const venue = await publishedVenue(request);
    const tap = await plantPlace(`Corner Tap ${tag}`, "Bar");
    const cafe = await plantPlace(`Corner Cafe ${tag}`, "Cafe");
    const chapel = await plantPlace(`Corner Chapel ${tag}`, "Church");
    const [act] = await seedEntities(tag, [{ name: "Corner Choir", type: "artist" }]);
    expect(act).toBeTruthy();
    const asked: { q: string; type: string | undefined }[] = [];
    await page.route("**/api/v1/public/picker", async (route) => {
      const body = route.request().postDataJSON() as { q: string; type?: string };
      asked.push({ q: body.q, type: body.type });
      if (body.type !== "place") return route.continue();
      // what the server answers for a place search, in the shape the server answers: names and addresses, nothing else. The chapel is
      // included to prove the page does not trust the search alone: the choose step refuses it.
      return route.fulfill({
        json: {
          items: [row(tap, "1 Invented Street, London"), row(cafe, "2 Invented Road, London"), row(chapel, "3 Invented Lane, London")],
          source: "qloo",
          message: null,
        },
      });
    });

    await page.goto(`/s/${venue.token}`);
    await page.getByRole("button", { name: "Start" }).click();
    await expect(page.getByRole("heading", { name: "What do you love?" })).toBeVisible();
    // places are a category of their own, beside the others
    const chips = page.getByRole("group", { name: "Search in" });
    await expect(chips.getByRole("button", { name: "Places" })).toBeVisible();
    await expect(page.getByLabel("Search", { exact: true })).toHaveAttribute("placeholder", "Band, show, film, book or brand");
    await chips.getByRole("button", { name: "Places" }).click();
    await expect(chips.getByRole("button", { name: "Places" })).toHaveAttribute("aria-pressed", "true");
    await expect(page.getByLabel("Search", { exact: true })).toHaveAttribute("placeholder", "A cafe, bar or restaurant near here");

    await page.getByLabel("Search", { exact: true }).fill("corner");
    await expect(page.getByRole("button", { name: `Add Corner Tap ${tag}` })).toBeVisible();
    // the guest sees a name, that it is a place, and an address to tell two branches apart
    const tapRow = page.getByRole("listitem").filter({ hasText: `Corner Tap ${tag}` });
    await expect(tapRow).toContainText("Place");
    await expect(tapRow).toContainText("1 Invented Street, London");
    expect(asked.some((a) => a.type === "place" && a.q === "corner")).toBe(true);
    await shot(page, info, "guest-places-results");
    await a11y(page, "place results");
    await setTheme(page, "dark");
    await shot(page, info, "guest-places-results", "dark");
    await a11y(page, "place results dark");
    await setTheme(page, "light");

    // a place that stands for a belief is refused when chosen, politely, and the guest carries on
    await page.getByRole("button", { name: `Add Corner Chapel ${tag}` }).click();
    await expect(page.getByRole("alert").filter({ hasText: "We can't use that one" })).toBeVisible();
    await expect(page.getByText("0 of 5 picked")).toBeVisible();
    await shot(page, info, "guest-places-refused");
    await a11y(page, "place refused");

    await page.getByRole("button", { name: `Add Corner Tap ${tag}` }).click();
    await expect(page.getByText("1 of 5 picked")).toBeVisible();
    await page.getByRole("button", { name: `Add Corner Cafe ${tag}` }).click();
    await expect(page.getByText("2 of 5 picked")).toBeVisible();

    // "All" never looks for places: they have their own chip (and an exact name near the room is not found among bands)
    await chips.getByRole("button", { name: "All" }).click();
    await page.getByLabel("Search", { exact: true }).fill(`Corner Choir ${tag}`);
    await expect(page.getByRole("button", { name: `Add Corner Choir ${tag}` })).toBeVisible();
    expect(asked.filter((a) => a.type === undefined).every((a) => !/place/i.test(a.type ?? ""))).toBe(true);
    await page.getByRole("button", { name: `Add Corner Choir ${tag}` }).click();
    await expect(page.getByText(/You can continue/)).toBeVisible();
    await expect(page.getByText("3 of 5 picked")).toBeVisible();
    await shot(page, info, "guest-places-picked");
    await a11y(page, "places picked");

    await page.getByRole("button", { name: "Continue" }).click();
    await page.getByRole("button", { name: "Send my picks" }).click();
    await expect(page.getByRole("heading", { name: "Your picks", level: 2 })).toBeVisible();
    await expect(page.getByText(`Corner Tap ${tag}`).first()).toBeVisible();
    await expect(page.getByText("Finding related tastes…")).toBeHidden({ timeout: 30_000 });
    await shot(page, info, "guest-places-card");
    await a11y(page, "card with places");

    // what was stored: the two places and the act as canonical ids with their types, and nothing about where the guest is
    const stored = await sql<{ entity_type: string; entity_id: string }>(
      "SELECT p.entity_type, p.entity_id FROM pick p JOIN response r ON r.id = p.response_id WHERE r.qr_point_id = $1 ORDER BY p.position",
      [venue.qrId],
    );
    expect(stored.rows.map((r) => r.entity_type)).toEqual(["urn:entity:place", "urn:entity:place", "urn:entity:artist"]);
    expect(stored.rows.map((r) => r.entity_id)).toEqual([tap.id, cafe.id, act]);
    const nothingStored = await sql("SELECT count(*)::int AS n FROM pick WHERE entity_id = $1", [chapel.id]);
    expect(nothingStored.rows[0]?.n).toBe(0);
    // the browser was never given the room's position, and never asked to send its own
    const picker = asked.filter((a) => a.type === "place");
    expect(picker.length).toBeGreaterThan(0);
    expect(JSON.stringify(asked)).not.toContain(String(LANTERN_ROW.lat));
    expect(problems.filter((p) => !/_rsc=|ERR_ABORTED/.test(p))).toEqual([]);
  });

  test("a survey that does not ask for places has no Places chip and refuses a place search", async ({ page, request }) => {
    const problems = watch(page);
    const venue = await publishedVenue(request, { questions: { picker_types: ["artist", "movie"] } });
    await page.goto(`/s/${venue.token}`);
    await page.getByRole("button", { name: "Start" }).click();
    const chips = page.getByRole("group", { name: "Search in" });
    await expect(chips.getByRole("button", { name: "Music" })).toBeVisible();
    await expect(chips.getByRole("button", { name: "Places" })).toHaveCount(0);
    const refused = await page.evaluate(async ({ token }) => {
      const survey = await (await fetch(`/api/v1/public/survey/${token}`)).json();
      const res = await fetch("/api/v1/public/picker", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ token, nonce: survey.nonce, q: "corner", type: "place" }) });
      return { status: res.status, detail: (await res.json()).detail };
    }, { token: venue.token });
    expect(refused.status).toBe(422);
    expect(refused.detail).toContain("not part of this survey");
    expect(problems.filter((p) => !/422|Failed to load resource|_rsc=|ERR_ABORTED/.test(p))).toEqual([]);
  });

  test("an owner can choose whether the survey asks for places, and a new survey asks for them", async ({ page, request }, info) => {
    const problems = watch(page);
    const venue = await publishedVenue(request);
    const survey = await (await request.get(`/api/v1/public/survey/${venue.token}`)).json();
    expect(survey.questions.picker_types).toContain("place");
    await signIn(page, venue.email);
    await page.goto("/app/survey");
    const places = page.getByRole("checkbox", { name: "Places" });
    await expect(places).toBeChecked();
    await shot(page, info, "owner-survey-places");
    await a11y(page, "owner survey with places");
    await places.uncheck();
    await page.getByRole("button", { name: "Publish" }).click();
    await expect(page.getByText(/Published as version/)).toBeVisible();
    const after = await (await request.get(`/api/v1/public/survey/${venue.token}`)).json();
    expect(after.questions.picker_types).not.toContain("place");
    expect(problems.filter((p) => !/_rsc=|ERR_ABORTED/.test(p))).toEqual([]);
  });
});
