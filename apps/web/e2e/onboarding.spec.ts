import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page } from "@playwright/test";
import http from "node:http";
import { resetRateLimits, setTheme, shot, signUp, sql, watch } from "./helpers";

// The API is started with NIGIWAI_NOMINATIM_URL=http://127.0.0.1:18089 and NIGIWAI_LLM_BASE_URL=http://127.0.0.1:18090 (see
// README, "Browser tests"). These servers play the address search and the model, so no question is sent to a service we do
// not run. The model stand-in behaves like a sensible interviewer: it records what the owner wrote when it can and asks
// for the next missing field otherwise, so the page and the API are exercised end to end.
const NOMINATIM_PORT = 18089;
const MODEL_PORT = 18090;
let nominatim: http.Server;
let model: http.Server;
let searches: string[] = [];
let prompts: string[] = [];

type Msg = { role: string; content: string | unknown[] };

const message = (content: unknown[]) => ({
  id: "msg_stub",
  type: "message",
  role: "assistant",
  model: "claude-stub",
  content,
  stop_reason: "tool_use",
  stop_sequence: null,
  usage: { input_tokens: 150, output_tokens: 40 },
});
const call = (name: string, input: unknown) => ({ type: "tool_use", id: `toolu_${Math.random().toString(36).slice(2, 12)}`, name, input });

function interviewer(first: string): unknown[] | null {
  if (first.includes("Fail now")) return null;
  if (first.includes('The owner has just written: "') && first.includes("coffee shop")) {
    return [
      call("record_answer", { field: "type", value: "cafe", quote: "coffee shop" }),
      call("record_answer", { field: "area", value: "12 Quill Street, Manchester", quote: "12 Quill Street, Manchester" }),
      call("record_answer", { field: "currency", value: "GBP", quote: "pounds" }),
      call("record_answer", { field: "type", value: "bar", quote: "nightclub downtown" }), // not what the owner said: refused
      call("ask_owner", { field: "goals", text: "What would you most like Nigiwai to help with?" }),
    ];
  }
  const left = /Fields still to learn, most useful first: \[('[a-z_]+'(?:, '[a-z_]+')*)\]/.exec(first);
  const next = left?.[1]?.split(", ")[0]?.replaceAll("'", "");
  if (!next) return [call("finish", {})];
  return [call("ask_owner", { field: next, text: `Tell me about the ${next.replaceAll("_", " ")}.` })];
}

test.beforeAll(async () => {
  nominatim = http.createServer((req, res) => {
    const q = (new URL(req.url ?? "/", "http://stub").searchParams.get("q") ?? "").toLowerCase();
    searches.push(q);
    res.setHeader("content-type", "application/json");
    if (q.includes("broken")) {
      res.statusCode = 503;
      res.end("busy");
      return;
    }
    if (q.includes("nowhere")) {
      res.end("[]");
      return;
    }
    res.end(
      JSON.stringify([
        { lat: "53.4808", lon: "-2.2426", display_name: "12, Quill Street, Manchester, England, United Kingdom" },
        { lat: "53.8008", lon: "-1.5491", display_name: "Quill Street, Leeds, England, United Kingdom" },
      ]),
    );
  });
  model = http.createServer((req, res) => {
    let raw = "";
    req.on("data", (c) => (raw += c));
    req.on("end", () => {
      const body = JSON.parse(raw || "{}") as { messages: Msg[] };
      const first = String(body.messages?.[0]?.content ?? "");
      if (body.messages.length === 1) prompts.push(first);
      const out = interviewer(first);
      res.setHeader("content-type", "application/json");
      if (out === null) {
        res.statusCode = 500;
        res.end(JSON.stringify({ type: "error", error: { type: "api_error", message: "down" } }));
        return;
      }
      res.end(JSON.stringify(message(out)));
    });
  });
  await Promise.all([
    new Promise<void>((resolve) => nominatim.listen(NOMINATIM_PORT, "127.0.0.1", resolve)),
    new Promise<void>((resolve) => model.listen(MODEL_PORT, "127.0.0.1", resolve)),
  ]);
});
test.afterAll(async () => {
  await Promise.all([new Promise<void>((resolve) => nominatim.close(() => resolve())), new Promise<void>((resolve) => model.close(() => resolve()))]);
});
test.beforeEach(async () => {
  searches = [];
  prompts = [];
  await resetRateLimits();
});

async function a11y(page: Page, label: string) {
  const result = await new AxeBuilder({ page }).analyze();
  expect(result.violations.map((v) => `${label}: ${v.id} ${v.nodes.map((n) => n.html.slice(0, 120)).join(" | ")}`)).toEqual([]);
}
// A link prefetch cancelled by a click is reported by Chrome as "aborted"; it is not a failure.
const prefetch = /requestfailed: GET \S+\?_rsc=\S+ net::ERR_ABORTED/;

const question = (page: Page, field: string) => expect(page.getByTestId("question")).toHaveAttribute("data-field", field);
const nav = (page: Page) => page.getByRole("navigation", { name: "Pages" });
/** On a phone the side menu is behind a button: open it for the checks, then close it so it does not cover the page. */
async function inMenu(page: Page, work: () => Promise<void>) {
  const toggle = page.getByRole("button", { name: "Menu" });
  const compact = await toggle.isVisible();
  if (compact) await toggle.click();
  await work();
  if (compact) await page.locator(".shell__scrim").click({ position: { x: 390, y: 300 } }); // a tap outside the menu closes it
}

test("onboarding: the fixed questions lead to a check, then a saved business and a plan that shapes the menu", async ({ page }, info) => {
  test.setTimeout(150_000);
  const problems = watch(page);
  const { email } = await signUp(page, "Quill Street Café");
  const where = `12 Quill Street, Manchester ${Date.now()}`;

  // the invitation on the overview leads in
  await expect(page.getByTestId("invite")).toBeVisible();
  await shot(page, info, "onboarding-invite");
  await page.getByRole("link", { name: "Tell Nigiwai about your business" }).click();
  await expect(page.getByRole("heading", { name: "Tell Nigiwai about your business", level: 1 })).toBeVisible();
  await shot(page, info, "onboarding-intro");
  await a11y(page, "intro");
  await page.getByRole("button", { name: "Use the fixed questions instead" }).click();

  // 1 of 8: kind of business (required, so there is no skip)
  await question(page, "type");
  await expect(page.getByTestId("progress")).toHaveText("Question 1 of at most 8");
  await expect(page.getByTestId("skip")).toHaveCount(0);
  await expect(page.getByTestId("log").getByRole("listitem").first()).toContainText("Hello. A few quick questions");
  await shot(page, info, "onboarding-q1");
  await a11y(page, "question 1");
  await page.getByRole("button", { name: "Café", exact: true }).click();

  // 2: the address, found on the map
  await question(page, "area");
  await expect(page.getByTestId("heard").locator('[data-field="type"] dd')).toHaveText("Café");
  await page.getByLabel("Address", { exact: true }).fill(where);
  await page.getByTestId("find-place").click();
  await expect(page.getByTestId("places").getByRole("button")).toHaveCount(2);
  await shot(page, info, "onboarding-places");
  await a11y(page, "places");
  await page.getByTestId("places").getByRole("button", { name: /Manchester/ }).click();

  // 3: goals (up to three)
  await question(page, "goals");
  await expect(page.getByTestId("heard").locator('[data-field="place"] dd')).toHaveText("Found on the map");
  await page.getByRole("button", { name: "Fill my quiet hours" }).click();
  await page.getByRole("button", { name: "Understand who my customers are" }).click();
  await page.getByRole("button", { name: "Book better acts" }).click();
  await expect(page.getByRole("button", { name: "Choose the right music to play" })).toBeDisabled(); // a fourth is not allowed
  await page.getByRole("button", { name: "Book better acts" }).click(); // take it back off
  await page.getByRole("button", { name: "Continue" }).click();

  // 4: currency
  await question(page, "currency");
  await expect(page.getByTestId("progress")).toHaveText("Question 4 of at most 8");
  await page.getByRole("button", { name: "GBP", exact: true }).click();

  // 5: opening hours (optional)
  await question(page, "hours");
  await expect(page.getByTestId("skip")).toBeVisible();
  await expect(page.getByRole("button", { name: "Save the hours" })).toBeDisabled();
  await page.getByRole("checkbox", { name: "Monday" }).check();
  await page.getByLabel("Monday opens").fill("08:00");
  await page.getByLabel("Monday closes").fill("17:00");
  await page.getByRole("button", { name: "Copy the first open day to every day" }).click();
  await page.getByRole("checkbox", { name: "Sunday" }).uncheck();
  await shot(page, info, "onboarding-hours");
  await a11y(page, "hours");
  await page.getByRole("button", { name: "Save the hours" }).click();

  // 6: live music (a café is asked)
  await question(page, "hosts_live_music");
  await page.getByRole("button", { name: "No", exact: true }).click();

  // the check
  await expect(page.getByRole("heading", { name: "Here is what I understood", level: 1 })).toBeVisible();
  const understood = page.getByTestId("understood");
  await expect(understood.locator('[data-field="type"] .onb-rows__v')).toHaveText("Café");
  await expect(understood.locator('[data-field="hours"] .onb-rows__v')).toHaveText("Mon-Sat 08:00-17:00, Sun closed");
  await expect(understood.locator('[data-field="hosts_live_music"] .onb-rows__v')).toHaveText("No");
  await expect(understood.locator('[data-field="goals"] .onb-rows__v')).toHaveText("Fill my quiet hours; Understand who my customers are");
  await expect(page.locator('[data-module="soundcheck"]')).toHaveAttribute("data-on", "false");
  await expect(page.locator('[data-module="soundcheck"] .onb-plan__why')).toContainText("Off because you do not host live music");
  await expect(page.locator('[data-module="today"] input')).toBeDisabled(); // core: always on
  await expect(page.locator('[data-module="grow"] input')).toBeDisabled(); // not built
  await expect(page.locator('[data-module="grow"] .onb-plan__why')).toContainText("Not built yet");
  await expect(page.getByLabel("Time zone")).not.toHaveValue("");
  await page.getByLabel("Time zone").fill("Europe/London");
  await shot(page, info, "onboarding-confirm");
  await a11y(page, "confirm");
  await setTheme(page, "dark");
  await shot(page, info, "onboarding-confirm", "dark");
  await a11y(page, "confirm dark");
  await setTheme(page, "light");

  // change an answer from the check, and switch a tool on by hand
  await page.getByRole("button", { name: "Change currency" }).click();
  await expect(page.getByTestId("edit")).toBeVisible();
  await page.getByTestId("edit").getByRole("button", { name: "EUR", exact: true }).click();
  await expect(understood.locator('[data-field="currency"] .onb-rows__v')).toHaveText("EUR");
  await expect(page.getByTestId("edit")).toHaveCount(0);
  await page.locator('[data-module="soundcheck"] input').check();
  await expect(page.locator('[data-module="soundcheck"]')).toHaveAttribute("data-on", "true");
  await page.getByLabel("Name").fill("Quill Street Café");
  await page.getByTestId("confirm").click();

  await expect(page.getByRole("heading", { name: "Saved", level: 1 })).toBeVisible();
  await shot(page, info, "onboarding-saved");
  await a11y(page, "saved");

  // what was written
  const biz = await sql("SELECT b.id, b.name, b.type, b.currency FROM business b WHERE b.tenant_id = (SELECT m.tenant_id FROM membership m JOIN app_user u ON u.id = m.user_id WHERE u.email = $1)", [email]);
  expect(biz.rows[0]).toMatchObject({ name: "Quill Street Café", type: "cafe", currency: "EUR" });
  const businessId = String(biz.rows[0]?.id);
  const loc = await sql("SELECT address, timezone, hours, ST_Y(geom::geometry) AS lat, ST_X(geom::geometry) AS lon FROM location WHERE business_id = $1", [businessId]);
  const place = loc.rows[0];
  expect(place?.address).toContain("Quill Street, Manchester");
  expect(place?.timezone).toBe("Europe/London");
  expect(place?.hours[0]).toEqual({ open: "08:00", close: "17:00" });
  expect(place?.hours[6]).toBeNull();
  expect(Number(place?.lat)).toBeCloseTo(53.4808, 3);
  expect(Number(place?.lon)).toBeCloseTo(-2.2426, 3);
  const plan = await sql("SELECT version, overrides FROM dashboard_plan WHERE business_id = $1", [businessId]);
  expect(plan.rows).toEqual([{ version: 1, overrides: { soundcheck: true } }]);
  expect(searches.filter((s) => s.includes("quill street"))).toHaveLength(1);

  // the menu now follows the plan: Soundcheck was switched on by hand, the Booking Brief is off
  await inMenu(page, async () => {
    await expect(nav(page).getByRole("link", { name: "Soundcheck" })).toBeVisible();
    await expect(nav(page).getByRole("link", { name: "Booking Brief" })).toHaveCount(0);
    await expect(nav(page).getByRole("link", { name: "Crowd map" })).toBeVisible();
  });
  await page.goto("/app");
  await expect(page.getByTestId("invite")).toHaveCount(0); // the invitation goes once the plan exists

  // the plan page: switch a tool off again, then change the answers
  await page.goto("/app/onboarding");
  await expect(page.getByRole("heading", { name: "Your plan", level: 1 })).toBeVisible();
  await expect(page.getByTestId("summary").locator('[data-field="currency"] dd')).toHaveText("EUR");
  await a11y(page, "plan");
  await page.locator('[data-module="soundcheck"] input').uncheck();
  await expect(page.locator('[data-module="soundcheck"]')).toHaveAttribute("data-on", "false");
  await expect.poll(async () => (await sql("SELECT max(version)::int AS v FROM dashboard_plan WHERE business_id = $1", [businessId])).rows[0]?.v).toBe(2);
  await inMenu(page, async () => {
    await expect(nav(page).getByRole("link", { name: "Soundcheck" })).toHaveCount(0);
  });
  await page.getByTestId("update").click();
  await expect(page.getByRole("heading", { name: "Here is what I understood", level: 1 })).toBeVisible(); // nothing left to ask
  await expect(page.getByTestId("understood").locator('[data-field="hours"] .onb-rows__v')).toHaveText("Mon-Sat 08:00-17:00, Sun closed");
  await page.getByTestId("confirm").click();
  await expect(page.getByRole("heading", { name: "Saved", level: 1 })).toBeVisible();
  expect((await sql("SELECT count(*)::int AS n FROM business_profile WHERE business_id = $1", [businessId])).rows[0]?.n).toBe(2);
  expect(problems.filter((p) => !prefetch.test(p))).toEqual([]);
});

test("onboarding: a refused answer says why, the address search fails gently, and the question stays", async ({ page }, info) => {
  test.setTimeout(100_000);
  const problems = watch(page);
  await signUp(page, "The Lamplighter");
  await page.goto("/app/onboarding");
  await page.getByRole("button", { name: "Use the fixed questions instead" }).click();
  await page.getByRole("button", { name: "Bar", exact: true }).click();
  await question(page, "area");

  await page.getByLabel("Address", { exact: true }).fill("a broken street");
  await page.getByTestId("find-place").click();
  await expect(page.getByText("The address search is not answering")).toBeVisible();
  await page.getByLabel("Address", { exact: true }).fill("nowhere in particular");
  await page.getByTestId("find-place").click();
  await expect(page.getByText("Nothing matched that.")).toBeVisible();
  await shot(page, info, "onboarding-no-match");
  await a11y(page, "no match");
  await page.getByTestId("use-typed").click(); // an address without a map position is allowed
  await question(page, "goals");
  await expect(page.getByTestId("heard").locator('[data-field="place"] dd')).toHaveText("Not placed yet");
  await page.getByRole("button", { name: "Book better acts" }).click();
  await page.getByRole("button", { name: "Continue" }).click();

  await question(page, "currency");
  await page.getByLabel("Another currency code").fill("xyz");
  await page.getByRole("button", { name: "Use this code" }).click();
  const alert = page.locator(".banner[data-tone='error']");
  await expect(alert).toContainText("Give a currency code such as USD, GBP or EUR.");
  await question(page, "currency"); // still the same question
  await shot(page, info, "onboarding-refused");
  await a11y(page, "refused");
  await page.getByLabel("Another currency code").fill("sek");
  await page.getByRole("button", { name: "Use this code" }).click();
  await question(page, "hours");
  await page.getByTestId("skip").click(); // optional: skipped
  await question(page, "hosts_live_music");
  await page.getByRole("button", { name: "Yes", exact: true }).click();
  await question(page, "show_nights");
  await expect(page.getByTestId("progress")).toHaveText("Question 7 of at most 8");
  await page.getByRole("button", { name: "Friday" }).click();
  await page.getByRole("button", { name: "Saturday" }).click();
  await page.getByRole("button", { name: "Continue" }).click();
  await question(page, "excluded_genres");
  await expect(page.getByTestId("progress")).toHaveText("Question 8 of at most 8");
  await page.getByLabel("Genres", { exact: true }).fill("metal, drill");
  await page.getByRole("button", { name: "Continue" }).click();

  // that was the eighth question; capacity is not a ninth, it is offered at the check
  await expect(page.getByRole("heading", { name: "Here is what I understood", level: 1 })).toBeVisible();
  const understood = page.getByTestId("understood");
  await expect(understood.locator('[data-field="currency"] .onb-rows__v')).toHaveText("SEK");
  await expect(understood.locator('[data-field="hours"] .onb-rows__v')).toHaveText("Not given");
  await expect(understood.locator('[data-field="excluded_genres"] .onb-rows__v')).toHaveText("metal, drill");
  await expect(understood.locator('[data-field="capacity"] .onb-rows__v')).toHaveText("Not given");
  await page.getByRole("button", { name: "Add room size" }).click();
  await page.getByLabel("People", { exact: true }).fill("120");
  await page.getByRole("button", { name: "Continue" }).click();
  await expect(understood.locator('[data-field="capacity"] .onb-rows__v')).toHaveText("About 120 people");
  await expect(page.locator('[data-module="soundcheck"]')).toHaveAttribute("data-on", "true");
  await expect(page.locator('[data-module="brief"]')).toHaveAttribute("data-on", "true");
  await shot(page, info, "onboarding-confirm-bar");
  await a11y(page, "confirm bar");

  // leaving without saving writes nothing
  await page.getByRole("button", { name: "Leave without saving" }).click();
  await expect(page.getByRole("heading", { name: "Tell Nigiwai about your business", level: 1 })).toBeVisible();
  await expect(page.getByTestId("start")).toBeVisible();
  expect(problems.filter((p) => !prefetch.test(p) && !/503|Failed to load resource|422/.test(p))).toEqual([]);
});

test("onboarding: the assistant reads what the owner writes, records only what they said, and asks for the rest", async ({ page }, info) => {
  test.setTimeout(120_000);
  const problems = watch(page);
  await signUp(page, "Quill Street Café");
  await page.goto("/app/onboarding");
  await page.getByTestId("start").click();
  await question(page, "type");
  await expect(page.getByLabel("Or tell me about it in your own words")).toBeVisible();
  await shot(page, info, "onboarding-assistant");
  await a11y(page, "assistant");

  await page.getByLabel("Or tell me about it in your own words").fill("We are a small coffee shop at 12 Quill Street, Manchester. We charge in pounds.");
  await page.getByRole("button", { name: "Send" }).click();
  await question(page, "goals");
  await expect(page.getByTestId("question")).toContainText("What would you most like Nigiwai to help with?");
  const heard = page.getByTestId("heard");
  await expect(heard.locator('[data-field="type"] dd')).toHaveText("Café"); // the invented "bar" with a quote the owner never wrote was refused
  await expect(heard.locator('[data-field="area"] dd')).toHaveText("12 Quill Street, Manchester");
  await expect(heard.locator('[data-field="currency"] dd')).toHaveText("GBP");
  await expect(page.getByTestId("progress")).toHaveText("Question 2 of at most 8");
  expect(prompts[0]).toContain("We are a small coffee shop");
  await shot(page, info, "onboarding-assistant-asked");

  await page.getByRole("button", { name: "Fill my quiet hours" }).click();
  await page.getByRole("button", { name: "Continue" }).click();
  // the stand-in model now asks for the remaining fields in turn: opening hours (skipped), then live music
  await question(page, "hours");
  await page.getByTestId("skip").click();
  await question(page, "hosts_live_music");
  await page.getByRole("button", { name: "No", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Here is what I understood", level: 1 })).toBeVisible();
  await expect(page.getByTestId("understood").locator('[data-field="area"] .onb-rows__v')).toHaveText("12 Quill Street, Manchester");
  await shot(page, info, "onboarding-assistant-confirm");
  await page.getByTestId("confirm").click();
  await expect(page.getByRole("heading", { name: "Saved", level: 1 })).toBeVisible();
  expect(problems.filter((p) => !prefetch.test(p))).toEqual([]);
});

test("onboarding: when the model is down the fixed questions take over and say so", async ({ page }, info) => {
  test.setTimeout(100_000);
  const problems = watch(page);
  await signUp(page, "The Lamplighter");
  await page.goto("/app/onboarding");
  await page.getByTestId("start").click();
  await question(page, "type");
  await page.getByLabel("Or tell me about it in your own words").fill("Fail now please");
  await page.getByRole("button", { name: "Send" }).click();
  await expect(page.locator(".banner[data-tone='warn']")).toContainText("The assistant is unavailable", { timeout: 40_000 });
  await question(page, "type"); // the unanswered question stays
  await expect(page.getByLabel("Or tell me about it in your own words")).toHaveCount(0); // plain questions from here
  await shot(page, info, "onboarding-fallback");
  await a11y(page, "fallback");
  await page.getByRole("button", { name: "Bar", exact: true }).click();
  await question(page, "area");
  expect(problems.filter((p) => !prefetch.test(p) && !/500|Failed to load resource/.test(p))).toEqual([]);
});
