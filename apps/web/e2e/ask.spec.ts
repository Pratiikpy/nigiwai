import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page } from "@playwright/test";
import http from "node:http";
import { plantArtist, publishedVenue, resetRateLimits, setTheme, shot, signIn, sql, watch } from "./helpers";

// The API is started with NIGIWAI_LLM_BASE_URL=http://127.0.0.1:18090 and a stand-in key (see README, "Browser tests").
// This server plays the model, so these tests never send a question to a service we do not run. Qloo is real: the stand-in
// reads the ids the real tools returned, exactly as a model would, and answers with a list that includes one item no tool
// returned, to see it refused.
const STUB_PORT = 18090;
let stub: http.Server;
const INVENTED_ID = "00000000-0000-4000-8000-0000000000aa";
let questions: string[] = [];

type Msg = { role: string; content: string | { type: string; content?: string; tool_use_id?: string }[] };

function lastResult(messages: Msg[]): unknown {
  const last = messages[messages.length - 1]?.content;
  if (!Array.isArray(last)) return null;
  const block = last.find((b) => b.type === "tool_result");
  try {
    return JSON.parse(block?.content ?? "null");
  } catch {
    return null;
  }
}

function message(content: unknown[]) {
  return {
    id: "msg_stub",
    type: "message",
    role: "assistant",
    model: "claude-stub",
    content,
    stop_reason: content.some((c) => (c as { type: string }).type === "tool_use") ? "tool_use" : "end_turn",
    stop_sequence: null,
    usage: { input_tokens: 120, output_tokens: 60 },
  };
}
const toolUse = (name: string, input: unknown) => ({ type: "tool_use", id: `toolu_${Math.random().toString(36).slice(2, 12)}`, name, input });

function respond(body: { messages: Msg[] }) {
  const first = String(body.messages[0]?.content ?? "");
  const turns = body.messages.filter((m) => m.role === "assistant").length;
  if (first.includes("Fail now")) return null;
  if (first.includes("Tell me nothing")) {
    return message([
      toolUse("answer", {
        verdict: "I cannot say anything useful about that yet.",
        items: [],
        evidence: [],
        what_would_change: ["Asking about a specific act or place."],
        not_enough_data: { reason: "The question names nothing I can look up.", unlock: ["Name an act, a film or a place."] },
      }),
    ]);
  }
  if (turns === 0) return message([toolUse("resolve_entity", { text: "Radiohead", type: "artist" })]);
  if (turns === 1) {
    const found = lastResult(body.messages) as { items?: { id: string }[] } | null;
    const id = found?.items?.[0]?.id;
    return message([toolUse("related", { type: "artist", seeds: id ? [id] : ["missing"], take: 6 })]);
  }
  const related = lastResult(body.messages) as { items?: { id: string; name: string }[]; error?: string } | null;
  const items = (related?.items ?? []).slice(0, 3);
  return message([
    toolUse("answer", {
      verdict: `${items[0]?.name ?? "Nothing"} is the closest match Qloo found, and Imaginary Moth Orchestra would suit you too.`,
      items: [
        ...items.map((i) => ({ entity_id: i.id, reason: "Qloo links this act to your question." })),
        { entity_id: INVENTED_ID, reason: "Imaginary Moth Orchestra is a perfect fit." },
      ],
      evidence: [
        { label: "observed", text: `Qloo returned ${related?.items?.length ?? 0} acts linked to the one you named.` },
        { label: "measured", text: "Your guests love it." },
      ],
      what_would_change: ["Naming a second act would narrow the list."],
      not_enough_data: null,
    }),
  ]);
}

test.beforeAll(async () => {
  stub = http.createServer((req, res) => {
    let raw = "";
    req.on("data", (c) => (raw += c));
    req.on("end", () => {
      const body = JSON.parse(raw || "{}") as { messages: Msg[] };
      if (body.messages?.length === 1) questions.push(String(body.messages[0]?.content));
      const out = respond(body);
      if (out === null) {
        res.statusCode = 500;
        res.setHeader("content-type", "application/json");
        res.end(JSON.stringify({ type: "error", error: { type: "api_error", message: "down" } }));
        return;
      }
      res.setHeader("content-type", "application/json");
      res.end(JSON.stringify(out));
    });
  });
  await new Promise<void>((resolve) => stub.listen(STUB_PORT, "127.0.0.1", resolve));
});
test.afterAll(async () => {
  await new Promise<void>((resolve) => stub.close(() => resolve()));
});
test.beforeEach(async () => {
  questions = [];
  await resetRateLimits();
});

async function a11y(page: Page, label: string) {
  const result = await new AxeBuilder({ page }).analyze();
  expect(result.violations.map((v) => `${label}: ${v.id} ${v.nodes.map((n) => n.html.slice(0, 120)).join(" | ")}`)).toEqual([]);
}
// Chrome reports a link prefetch cancelled by a click, and a finished event-stream request when the page is reloaded,
// as "aborted". Neither is a failure: the stream has ended by then (the next question is asked from the same page).
const prefetch = /requestfailed: (GET \S+[?&]_rsc=\S+|POST \S+\/ask) net::ERR_ABORTED/;

test("ask: a question streams its steps, then an answer with only what Qloo returned, and the trace opens", async ({ page, request }, info) => {
  test.setTimeout(150_000);
  const problems = watch(page);
  const venue = await publishedVenue(request);
  await plantArtist("Radiohead", ["Alternative rock"]).catch(() => undefined); // a stored act does not change what Qloo answers
  await signIn(page, venue.email);
  await page.goto("/app/ask");
  await expect(page.getByRole("heading", { name: "Ask Nigiwai", level: 1 })).toBeVisible();
  await expect(page.getByRole("heading", { name: "What do you want to know about your crowd?" })).toBeVisible();
  await shot(page, info, "ask-empty");
  await a11y(page, "ask empty");

  await page.getByRole("button", { name: "About the culture" }).click();
  await expect(page.getByRole("heading", { name: "What do you want to know about taste and culture?" })).toBeVisible();
  await page.getByLabel("Your question").fill("Who is like Radiohead?");
  await page.getByRole("button", { name: "Ask", exact: true }).click();

  const answer = page.getByTestId("answer");
  await expect(answer).toBeVisible({ timeout: 90_000 });
  expect(questions).toEqual(["Question from the owner: Who is like Radiohead?"]);
  const steps = page.getByTestId("step");
  await expect(steps).toHaveCount(2);
  await expect(steps.nth(0)).toContainText("Looking the item up in Qloo");
  await expect(steps.nth(1)).toContainText("Asking Qloo what is linked to it");
  await expect(page.getByTestId("steps")).toContainText("Checked in 2 steps");

  // three real acts Qloo returned; the invented one and its name are gone
  const items = page.getByTestId("item");
  await expect(items).toHaveCount(3);
  for (const it of await items.all()) await expect(it).toHaveAttribute("data-provenance", "surfaced");
  await expect(answer).not.toContainText("Imaginary Moth Orchestra");
  await expect(page.getByTestId("verdict")).toContainText("[a name Qloo did not return]");
  await expect(page.getByTestId("validator")).toContainText("3 items listed, each returned by a Qloo call during this question.");
  await expect(page.getByTestId("validator")).toContainText("1 more the assistant proposed was left out");
  // a label has to be earned: the model said "measured", but nothing from the owner's data was read
  const labels = await page.getByTestId("evidence").locator(".lbl__t").allInnerTexts();
  expect(labels).toEqual(["Observed", "Modelled"]);
  await expect(page.getByTestId("note").first()).toContainText("removed because no Qloo call returned");
  await shot(page, info, "ask-answer");
  await a11y(page, "ask answer");
  await setTheme(page, "dark");
  await shot(page, info, "ask-answer", "dark");
  await a11y(page, "ask answer dark");
  await setTheme(page, "light");

  // the trace lists the real Qloo calls and their results, and what was sent
  await page.getByTestId("trace-button").click();
  const trace = page.getByTestId("trace");
  await expect(trace).toBeVisible();
  const calls = page.getByTestId("calls").locator("> li");
  await expect(calls.first()).toBeVisible({ timeout: 20_000 });
  expect(await calls.count()).toBeGreaterThanOrEqual(2);
  await expect(page.getByTestId("calls")).toContainText("/search");
  await expect(page.getByTestId("calls")).toContainText("/v2/insights");
  await shot(page, info, "ask-trace");
  await a11y(page, "ask trace");

  // a refresh restores the answer; it was stored
  await page.reload();
  await expect(page.getByTestId("answer")).toBeVisible({ timeout: 20_000 });
  await expect(page.getByTestId("item")).toHaveCount(3);
  expect((await sql("SELECT count(*)::int AS n FROM ask_answer WHERE business_id = $1", [venue.businessId])).rows[0]?.n).toBe(1);
  expect(problems.filter((p) => !prefetch.test(p))).toEqual([]);
});

test("ask: not enough data is said plainly with what would unlock it, and a model outage still leaves a plain answer", async ({ page, request }, info) => {
  test.setTimeout(120_000);
  const problems = watch(page);
  const venue = await publishedVenue(request);
  await signIn(page, venue.email);
  await page.goto("/app/ask");

  await page.getByLabel("Your question").fill("Tell me nothing");
  await page.getByRole("button", { name: "Ask", exact: true }).click();
  await expect(page.getByTestId("not-enough")).toBeVisible({ timeout: 60_000 });
  await expect(page.getByTestId("not-enough")).toContainText("Name an act, a film or a place.");
  await expect(page.getByTestId("validator")).toContainText("Nothing was listed.");
  await shot(page, info, "ask-not-enough");
  await a11y(page, "ask not enough");

  await page.getByLabel("Your question").fill("Fail now please");
  await page.getByRole("button", { name: "Ask", exact: true }).click();
  const second = page.getByTestId("answer").nth(1);
  await expect(second).toBeVisible({ timeout: 60_000 });
  await expect(second).toHaveAttribute("data-kind", "template");
  await expect(second.getByTestId("verdict")).toContainText("Nothing could be found for that question.");
  await expect(second).toContainText("AI service");
  // both are kept and listed
  await page.reload();
  await expect(page.getByTestId("past").getByRole("button")).toHaveCount(2);
  expect(problems.filter((p) => !prefetch.test(p) && !/500/.test(p))).toEqual([]);
});

test("ask: the page says so up front when no AI service is connected", async ({ page, request }, info) => {
  const problems = watch(page);
  const venue = await publishedVenue(request);
  await signIn(page, venue.email);
  await page.route("**/api/v1/tenants/*/businesses/*/ask", async (route) => {
    if (route.request().method() === "POST") {
      await route.fulfill({
        status: 503,
        contentType: "application/json",
        body: JSON.stringify({ detail: "Ask Nigiwai needs an AI service, and none is connected to this server." }),
      });
    } else await route.continue();
  });
  await page.goto("/app/ask");
  await page.getByRole("button", { name: "What could fill my quietest hours?" }).click();
  await expect(page.getByText("Ask Nigiwai needs an AI service, and none is connected to this server.")).toBeVisible();
  await expect(page.getByLabel("Your question")).toBeDisabled(); // nothing more to type until it is connected
  await expect(page.getByTestId("turn")).toHaveCount(0);
  await shot(page, info, "ask-unavailable");
  await a11y(page, "ask unavailable");
  expect(problems.filter((p) => !prefetch.test(p) && !/503|Failed to load resource/.test(p))).toEqual([]);
});
