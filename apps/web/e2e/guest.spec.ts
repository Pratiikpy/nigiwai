import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page } from "@playwright/test";
import { publishedVenue, resetRateLimits, seedEntities, setTheme, shot, sql, watch } from "./helpers";

const tag = `e2e${Date.now().toString(36)}`;
const NAMES = ["Moonlit Choir", "Moonbeam Radio", "Moonstone Station", "Moor Lane Band"];

async function a11y(page: Page, label: string) {
  const result = await new AxeBuilder({ page }).analyze();
  expect(result.violations.map((v) => `${label}: ${v.id} (${v.nodes.length}) ${v.nodes.map((n) => n.html.slice(0, 160)).join(" | ")}`)).toEqual([]);
}

async function search(page: Page, text: string) {
  await page.getByLabel("Search", { exact: true }).fill(text);
}

test.describe("the guest survey", () => {
  test.beforeEach(async () => resetRateLimits());

  test("a guest scans, picks, answers, sends, and removes their answers", async ({ page, request }, info) => {
    const problems = watch(page);
    const venue = await publishedVenue(request, { reward: { title: "A free coffee", detail: "Show this screen at the bar." } });
    const ids = await seedEntities(tag, NAMES.map((name) => ({ name, type: "artist" })));

    await page.goto(`/s/${venue.token}`);

    // 1. Consent: the heading, the reward, and what is and is not collected.
    await expect(page.getByRole("heading", { name: /Tell us what you love/, level: 1 })).toBeVisible();
    await expect(page.getByText("A free coffee")).toBeVisible();
    await expect(page.getByText("Your name or email")).toBeVisible();
    await shot(page, info, "guest-1-consent");
    await a11y(page, "consent");

    // The notice sheet opens, reads the server's consent text, traps focus and closes on Escape.
    await page.getByRole("button", { name: "Read the full notice" }).click();
    const notice = page.getByRole("dialog", { name: "How your picks are used" });
    await expect(notice).toBeVisible();
    await expect(notice.getByText("What we never collect.")).toBeVisible();
    await shot(page, info, "guest-1b-notice");
    await a11y(page, "notice");
    await page.keyboard.press("Escape");
    await expect(notice).toBeHidden();

    // 2. The picker.
    await page.getByRole("button", { name: "Start" }).click();
    await expect(page.getByRole("heading", { name: "What do you love?" })).toBeVisible();
    await expect(page.getByRole("button", { name: "Continue" })).toBeDisabled();
    await expect(page.getByText("Pick at least 3 to continue.")).toBeVisible();
    await shot(page, info, "guest-2-pick-empty");
    await a11y(page, "picker idle");

    await search(page, `Moon`);
    // The suffix tag keeps this run's items apart from any other run's.
    await search(page, `Moon ${tag}`);
    await expect(page.getByRole("button", { name: `Add Moonlit Choir ${tag}` })).toBeVisible();
    await shot(page, info, "guest-2b-results");
    await a11y(page, "picker results");

    await page.getByRole("button", { name: `Add Moonlit Choir ${tag}` }).click();
    await expect(page.getByRole("button", { name: `Remove Moonlit Choir ${tag}`, exact: true }).first()).toBeVisible();
    await expect(page.getByText("Pick 2 more to continue.")).toBeVisible();
    await page.getByRole("button", { name: `Add Moonbeam Radio ${tag}` }).click();
    await expect(page.getByText("Pick 1 more to continue.")).toBeVisible();
    await expect(page.getByRole("button", { name: "Continue" })).toBeDisabled();
    await page.getByRole("button", { name: `Add Moonstone Station ${tag}` }).click();
    await expect(page.getByText(/You can continue/)).toBeVisible();
    await expect(page.getByText("3 of 5 picked")).toBeVisible();
    await shot(page, info, "guest-2c-three-picked");

    // A reload keeps the picks (the draft lives in this tab only).
    await page.reload();
    await page.getByRole("button", { name: "Start" }).click();
    await expect(page.getByText("3 of 5 picked")).toBeVisible();

    // 3. About you and the send list.
    await page.getByRole("button", { name: "Continue" }).click();
    await expect(page.getByRole("heading", { name: "A little about you" })).toBeVisible();
    await page.getByRole("button", { name: "25–34" }).click();
    await page.getByLabel("Where do you usually spend your day?").fill("Eastside");
    await page.getByRole("button", { name: "$$ Somewhere in the middle" }).click();
    await expect(page.getByText("age range 25–34, area Eastside, spend $$")).toBeVisible();
    await shot(page, info, "guest-3-about");
    await a11y(page, "about");

    // 4. Send.
    await page.getByRole("button", { name: "Send my picks" }).click();
    // The card: this venue has no crowd yet, so it says so instead of inventing a group.
    await expect(page.getByRole("heading", { level: 1 })).toContainText("still forming");
    await expect(page.getByText("A free coffee")).toBeVisible();
    await expect(page.getByRole("heading", { name: "Your picks", level: 2 })).toBeVisible();
    const receipt = (await page.getByTestId("receipt").textContent())?.trim() ?? "";
    expect(receipt.length).toBeGreaterThanOrEqual(20);
    // The fill-in settles one way or the other: these picks are invented, so Qloo has nothing to relate them to and the
    // simple card stays with its explanation.
    await expect(page.getByText("Finding related tastes…")).toBeHidden({ timeout: 30_000 });
    await expect(page.getByText(/The extras (are slow|aren.t available) right now/)).toBeVisible();
    await shot(page, info, "guest-4-done");
    await a11y(page, "done");

    // Sharing: a picture made on the server from names only.
    await page.getByRole("button", { name: "Share my card" }).click();
    const share = page.getByRole("dialog", { name: "Share your card" });
    await expect(share.getByRole("img", { name: /Your Taste Card/ })).toBeVisible({ timeout: 15_000 });
    await expect(share.getByRole("link", { name: "Save image" })).toBeVisible();
    await shot(page, info, "guest-4b-share");
    await a11y(page, "share");
    await page.keyboard.press("Escape");
    await expect(share).toBeHidden();

    // What was stored: exactly the three picks and the three answers, nothing identifying.
    const rows = await sql<{ age_band: string; district: string; budget: number; quality_flag: string; n: string }>(
      "SELECT r.age_band, r.district, r.budget, r.quality_flag, (SELECT count(*) FROM pick p WHERE p.response_id = r.id) AS n FROM response r WHERE r.qr_point_id = $1",
      [venue.qrId],
    );
    expect(rows.rows).toEqual([{ age_band: "25-34", district: "Eastside", budget: 2, quality_flag: "ok", n: "3" }]);
    const picked = await sql<{ entity_id: string }>(
      "SELECT entity_id FROM pick WHERE response_id = (SELECT id FROM response WHERE qr_point_id = $1) ORDER BY position",
      [venue.qrId],
    );
    expect(picked.rows.map((r) => r.entity_id)).toEqual(ids.slice(0, 3));

    // 5. Remove the answers with the receipt.
    await page.getByRole("button", { name: "Remove my answers" }).first().click();
    const sheet = page.getByRole("alertdialog", { name: "Remove your answers?" });
    await expect(sheet.getByLabel("Receipt code")).toHaveValue(receipt);
    await shot(page, info, "guest-5-remove");
    await sheet.getByRole("button", { name: "Remove my answers" }).click();
    await expect(sheet.getByText("Removed.")).toBeVisible();
    expect((await sql("SELECT count(*) AS n FROM response WHERE qr_point_id = $1", [venue.qrId])).rows[0]).toEqual({ n: "0" });
    expect((await sql("SELECT count(*) AS n FROM pick WHERE entity_id = ANY($1)", [ids])).rows[0]).toEqual({ n: "0" });

    expect(problems).toEqual([]);
  });

  test("dark theme renders the same screens", async ({ page, request }, info) => {
    const problems = watch(page);
    const venue = await publishedVenue(request, { reward: { title: "A free coffee", detail: "" } });
    await page.goto(`/s/${venue.token}`);
    await expect(page.getByRole("heading", { name: /Tell us what you love/ })).toBeVisible();
    await setTheme(page, "dark");
    await shot(page, info, "guest-1-consent", "dark");
    await a11y(page, "consent dark");
    await page.getByRole("button", { name: "Start" }).click();
    await shot(page, info, "guest-2-pick-empty", "dark");
    await a11y(page, "picker dark");
    expect(problems).toEqual([]);
  });

  test("a code that is unknown, turned off or unpublished all say the same thing", async ({ page, request }, info) => {
    const problems = watch(page);
    const venue = await publishedVenue(request);
    const me = await (await request.get("/api/v1/auth/me")).json();
    await request.post(`/api/v1/tenants/${me.tenants[0].id}/qr-points/${venue.qrId}/revoke`, { headers: { "x-csrf-token": me.csrf_token } });
    for (const token of ["A".repeat(24), venue.token, "short"]) {
      await page.goto(`/s/${token}`);
      await expect(page.getByRole("heading", { name: "This survey isn’t open right now." })).toBeVisible();
    }
    await shot(page, info, "guest-closed");
    await a11y(page, "closed");
    // The browser logs a failed fetch for the 404s it just made; those are the expected answers, not defects.
    expect(problems.filter((p) => !p.includes("404"))).toEqual([]);
  });

  test("the search failing, then working again", async ({ page, request }, info) => {
    const problems = watch(page);
    const venue = await publishedVenue(request);
    await seedEntities(tag, [{ name: "Retry Quartet", type: "artist" }]);
    await page.goto(`/s/${venue.token}`);
    await page.getByRole("button", { name: "Start" }).click();

    let fail = true;
    await page.route("**/api/v1/public/picker", (route) => (fail ? route.abort("connectionrefused") : route.continue()));
    await search(page, `Retry ${tag}`);
    await expect(page.getByRole("heading", { name: "We couldn’t reach the search." })).toBeVisible();
    await expect(page.getByText("Your picks are safe on this phone.")).toBeVisible();
    await shot(page, info, "guest-picker-error");
    await a11y(page, "picker error");
    fail = false;
    await page.getByRole("button", { name: "Try again" }).click();
    await expect(page.getByRole("button", { name: `Add Retry Quartet ${tag}` })).toBeVisible();
    expect(problems.filter((p) => !p.includes("connectionrefused") && !p.includes("ERR_CONNECTION_REFUSED") && !p.includes("net::ERR"))).toEqual([]);
  });

  test("nothing found, a rate limit, and an expired page are each handled", async ({ page, request }, info) => {
    const problems = watch(page);
    const venue = await publishedVenue(request);
    const [id] = await seedEntities(tag, [{ name: "Expiry Ensemble", type: "artist" }]);
    await page.goto(`/s/${venue.token}`);
    await page.getByRole("button", { name: "Start" }).click();

    await page.route("**/api/v1/public/picker", (route) =>
      route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ items: [], source: "none", message: null }) }),
    );
    await search(page, "zzzzqq nothing here");
    await expect(page.getByRole("heading", { name: /Nothing called/ })).toBeVisible();
    await shot(page, info, "guest-picker-empty");
    await a11y(page, "picker empty");

    await page.unroute("**/api/v1/public/picker");
    // The server says "too many requests".
    await page.route("**/api/v1/public/picker", (route) =>
      route.fulfill({ status: 429, contentType: "application/json", body: JSON.stringify({ detail: "Too many requests from this network. Please wait a moment." }) }),
    );
    await search(page, `Expiry ${tag}`);
    await expect(page.getByText(/That's a lot in a short time/)).toBeVisible();
    await page.unroute("**/api/v1/public/picker");

    // The page's nonce expired: the app fetches a fresh one and retries without bothering the guest.
    let expired = true;
    await page.route("**/api/v1/public/picker", (route) => {
      if (expired) {
        expired = false;
        return route.fulfill({ status: 403, contentType: "application/json", body: JSON.stringify({ detail: "This page has expired. Reload it to continue." }) });
      }
      return route.continue();
    });
    await page.getByRole("button", { name: "Try again" }).click();
    await expect(page.getByRole("button", { name: `Add Expiry Ensemble ${tag}` })).toBeVisible();
    expect(id).toBeTruthy();
    expect(problems.filter((p) => !/40[34]|429/.test(p))).toEqual([]);
  });

  test("a pick Qloo cannot use is refused politely and the guest carries on", async ({ page, request }, info) => {
    const problems = watch(page);
    const venue = await publishedVenue(request);
    const [bad, ok] = await seedEntities(tag, [
      { name: "Refused Reading", type: "book" },
      { name: "Refused Radio", type: "podcast" },
    ]);
    await sql("UPDATE qloo_entity SET insights_eligible = NULL WHERE entity_id = ANY($1)", [[bad, ok]]);
    await page.goto(`/s/${venue.token}`);
    await page.getByRole("button", { name: "Start" }).click();
    // The real probe needs Qloo; here the answer is scripted so the refusal path is exercised.
    await page.route("**/api/v1/public/select", async (route) => {
      const body = route.request().postDataJSON() as { entity_id: string };
      if (body.entity_id === bad) {
        return route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({ entity_id: bad, eligible: false, message: "We can't use that one for this survey. Please choose another favourite." }),
        });
      }
      return route.continue();
    });
    await search(page, `Refused ${tag}`);
    await page.getByRole("button", { name: `Add Refused Reading ${tag}` }).click();
    await expect(page.getByRole("alert").filter({ hasText: "We can't use that one" })).toBeVisible();
    await expect(page.getByText("0 of 5 picked")).toBeVisible();
    await shot(page, info, "guest-pick-refused");
    await a11y(page, "pick refused");
    expect(problems).toEqual([]);
  });

  test("removing answers with a wrong code says so", async ({ page, request }, info) => {
    const problems = watch(page);
    const venue = await publishedVenue(request);
    await page.goto(`/s/${venue.token}`);
    await page.getByRole("button", { name: "Remove my answers" }).click();
    const sheet = page.getByRole("alertdialog", { name: "Remove your answers?" });
    await sheet.getByLabel("Receipt code").fill("not-a-real-code-1234");
    await sheet.getByRole("button", { name: "Remove my answers" }).click();
    await expect(sheet.getByText(/couldn.t find that code/)).toBeVisible();
    await sheet.getByLabel("Receipt code").fill("short");
    await sheet.getByRole("button", { name: "Remove my answers" }).click();
    await expect(sheet.getByText("Enter the whole receipt code.")).toBeVisible();
    await shot(page, info, "guest-remove-wrong");
    await a11y(page, "remove wrong");
    expect(problems).toEqual([]);
  });
});
