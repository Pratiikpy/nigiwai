import { mkdirSync } from "node:fs";
import { expect, test, type Page } from "@playwright/test";
import { publishedVenue, resetRateLimits, setTheme, signIn, sql } from "./helpers";
import { fittedShowcase, openAllWeek, plantShowcaseActs, plantShowcaseCrowd, SCENES } from "./showcase-data";

// The screenshots in docs/screenshots (README, "Screenshots"). They are made on request, not on every run, so a normal run never rewrites
// the images: NIGIWAI_SHOWCASE=1 npx playwright test e2e/showcase.spec.ts. The owner and guest screens show a made-up room with made-up
// guests and acts (showcase-data.ts): no Qloo data, and no account of a real person. The real demo venues are deliberately not pictured
// here: their screens carry Qloo-derived names, and the only ones in the repository are the sample briefs (docs/HUMAN.md, H8).
test.skip(process.env.NIGIWAI_SHOWCASE !== "1", "set NIGIWAI_SHOWCASE=1 to make the README screenshots");

const OUT = "../../docs/screenshots";
mkdirSync(OUT, { recursive: true });

async function snap(page: Page, name: string) {
  await page.waitForTimeout(700); // colour transitions and the last paint
  await page.screenshot({ path: `${OUT}/${name}.png`, fullPage: false });
}

test.beforeEach(async () => resetRateLimits());

test("owner workspace and public pages, on a desktop", async ({ page, request }, info) => {
  test.skip(info.project.name !== "desktop", "the owner screens are shown at desktop width");
  test.setTimeout(900_000);
  const venue = await publishedVenue(request, { reward: { title: "A free coffee", detail: "Show this screen at the bar." } });
  await sql("UPDATE business SET name = 'The Lantern Room' WHERE id = $1", [venue.businessId]);
  await sql("UPDATE tenant SET name = 'The Lantern Room' WHERE id = $1", [venue.tenantId]);
  await openAllWeek(venue.businessId);
  await plantShowcaseCrowd(venue.businessId, venue.qrId, 225);
  const fitted = await fittedShowcase(venue.businessId);
  expect(fitted.shown.length).toBeGreaterThanOrEqual(2);
  await plantShowcaseActs(venue.tenantId, venue.businessId, fitted.shown, fitted.version);
  const email = "owner@thelanternroom.example";
  await sql("UPDATE app_user SET email = 'earlier-' || id || '@example.com' WHERE email = $1", [email]); // a run before this one used the address
  await sql("UPDATE app_user SET email = $1 WHERE email = $2", [email, venue.email]);
  await signIn(page, email);

  const heading = async (name: string | RegExp) => expect(page.getByRole("heading", { name, level: 1 })).toBeVisible({ timeout: 30_000 });

  await page.goto("/app");
  await heading(/Overview|The Lantern Room/);
  await snap(page, "owner-overview");

  await page.goto("/app/today");
  await heading("Today");
  await expect(page.getByTestId("quiet")).toBeVisible();
  await expect(page.getByTestId("action").first()).toBeVisible();
  await snap(page, "owner-today");

  await page.goto("/app/people");
  await heading("My people");
  await expect(page.getByText("Named groups")).toBeVisible();
  await snap(page, "owner-my-people");

  await page.goto("/app/map?layers=sites,groups");
  await heading("Crowd map");
  const map = page.locator(".crowdmap");
  await expect(map).toHaveAttribute("data-ready", "1", { timeout: 40_000 });
  // open the site: the room sits at the middle of the map, and the inspector then says what the circle is made of
  const box = (await map.boundingBox())!;
  await page.mouse.click(box.x + box.width / 2, box.y + box.height / 2);
  await expect(page.getByText("Select something on the map")).toBeHidden({ timeout: 10_000 }).catch(() => undefined);
  await snap(page, "owner-crowd-map");

  await page.goto("/app/soundcheck");
  await heading("Soundcheck");
  await expect(page.getByRole("group", { name: "Suggested acts" }).getByRole("button").first()).toBeVisible({ timeout: 30_000 });
  await snap(page, "owner-soundcheck");
  // a stored verdict: the score, its range, each group's rank and the working
  await page.getByRole("region", { name: "Recent Soundchecks" }).getByRole("button", { name: /Juniper Hours and the Slow Tide/ }).click();
  await expect(page.getByTestId("verdict")).toBeVisible({ timeout: 30_000 });
  await expect(page.getByTestId("score")).toBeVisible();
  await page.waitForTimeout(700);
  // the card alone: the AI-alone panel beside it asks a live service about an invented act, so it is left out of the picture
  await page.getByTestId("verdict").screenshot({ path: `${OUT}/owner-verdict.png` });

  await page.goto("/app/sound");
  await heading("Sound plan");
  await expect(page.getByText("Monday to Thursday")).toBeVisible({ timeout: 30_000 });
  await snap(page, "owner-sound-plan");

  await page.goto("/app/brief");
  await heading("Booking Brief");
  await expect(page.getByText("Three acts to consider").first()).toBeVisible({ timeout: 30_000 });
  await snap(page, "owner-booking-brief");

  await page.goto("/app/survey");
  await heading("Survey");
  await snap(page, "owner-survey-builder");

  // the public pages, light and dark
  for (const [path, name] of [
    ["/", "landing"],
    ["/try", "try-a-venue"],
    ["/evidence", "evidence"],
    ["/privacy", "privacy"],
    ["/business", "business-case"],
  ] as const) {
    await page.context().clearCookies();
    await page.goto(path);
    await expect(page.getByRole("heading", { level: 1 }).first()).toBeVisible();
    await page.waitForLoadState("networkidle").catch(() => undefined);
    await snap(page, `public-${name}`);
    if (name === "landing" || name === "try-a-venue") {
      await setTheme(page, "dark");
      await snap(page, `public-${name}-dark`);
      await setTheme(page, "light");
    }
  }
});

test("the guest survey and the Taste Card, on a phone", async ({ page, request }, info) => {
  test.skip(info.project.name !== "phone", "the guest screens are shown at phone width");
  test.setTimeout(600_000);
  const venue = await publishedVenue(request, { reward: { title: "A free coffee", detail: "Show this screen at the bar." } });
  await sql("UPDATE business SET name = 'The Lantern Room' WHERE id = $1", [venue.businessId]);
  await sql("UPDATE tenant SET name = 'The Lantern Room' WHERE id = $1", [venue.tenantId]);
  const scenes = await plantShowcaseCrowd(venue.businessId, venue.qrId, 225, 9);
  await fittedShowcase(venue.businessId);
  const mine = scenes[0]!;
  const act = mine.find((i) => i.urn.endsWith("artist"))!;
  const film = mine.find((i) => i.urn.endsWith("movie"))!;
  const brand = mine.find((i) => i.urn.endsWith("brand"))!;

  // The picker falls back to a live Qloo search when a name has few saved matches, and an invented name's nearest neighbours are real items
  // with Qloo's own descriptions. Those are dropped from what the picture shows: only the room's invented names are pictured.
  const invented = new Set(SCENES.flatMap((s) => [...s.acts, ...s.films, ...s.brands]));
  await page.route("**/api/v1/public/picker", async (route) => {
    const response = await route.fetch();
    const body = (await response.json()) as { items?: { name: string }[] };
    await route.fulfill({ response, json: { ...body, items: (body.items ?? []).filter((i) => invented.has(i.name)) } });
  });

  await page.goto(`/s/${venue.token}`);
  await expect(page.getByRole("heading", { name: /Tell us what you love/, level: 1 })).toBeVisible();
  await snap(page, "guest-1-welcome");
  await page.getByRole("button", { name: "Start" }).click();
  await expect(page.getByRole("heading", { name: "What do you love?" })).toBeVisible();
  await page.getByLabel("Search", { exact: true }).fill(act.name.slice(0, 7));
  await expect(page.getByRole("button", { name: `Add ${act.name}` }).first()).toBeVisible({ timeout: 15_000 }); // earlier runs left the same names
  await snap(page, "guest-2-search");
  for (const item of [act, film, brand]) {
    await page.getByLabel("Search", { exact: true }).fill(item.name);
    await page.getByRole("button", { name: `Add ${item.name}` }).first().click();
  }
  await expect(page.getByText("3 of 5 picked")).toBeVisible();
  await snap(page, "guest-3-picked");
  await page.getByRole("button", { name: "Continue" }).click();
  await snap(page, "guest-4-about-you");
  await page.getByRole("button", { name: "Send my picks" }).click();
  await expect(page.getByRole("heading", { name: "Your strongest picks" })).toBeVisible();
  // the top of the card: the group the guest matches and their own picks. What fills in below it asks Qloo about these invented names, which it
  // cannot answer, so that part is left out of the picture rather than shown as an error.
  await page.waitForTimeout(700);
  const width = page.viewportSize()?.width ?? 412;
  await page.screenshot({ path: `${OUT}/guest-5-taste-card.png`, clip: { x: 0, y: 0, width, height: 640 } });
});
