import { randomUUID } from "node:crypto";
import { expect, type APIRequestContext, type Page, type TestInfo } from "@playwright/test";
import pg from "pg";
import { createClient } from "redis";

export const PASSWORD = "a-long-passphrase-9x";
const ADMIN = process.env.NIGIWAI_E2E_DB ?? "postgresql://nigiwai:nigiwai-dev-only@127.0.0.1:55432/nigiwai";

export async function sql<T extends pg.QueryResultRow = pg.QueryResultRow>(text: string, values: unknown[] = []) {
  const client = new pg.Client({ connectionString: ADMIN });
  await client.connect();
  try {
    return await client.query<T>(text, values);
  } finally {
    await client.end();
  }
}

/** Invented items, as if earlier searches had registered them. The names carry a run tag so runs do not collide. */
export async function seedEntities(tag: string, items: { name: string; type: string }[]): Promise<string[]> {
  const ids: string[] = [];
  for (const item of items) {
    const id = randomUUID();
    ids.push(id);
    const urn = `urn:entity:${item.type}`;
    await sql(
      "INSERT INTO qloo_entity (entity_id, type, types, name_nfc, props, insights_eligible) VALUES ($1, $2, $3, $4, $5, true)",
      [id, urn, [urn], `${item.name} ${tag}`, JSON.stringify({ release_year: 2001, description: `${item.name}, an invented entry.` })],
    );
  }
  return ids;
}

/** The API rate-limits sign-ups and sign-ins per network address, as it should. The tests share one address, so each
 * test clears the counters first; nothing else in Redis is touched. */
export async function resetRateLimits(): Promise<void> {
  const client = createClient({ url: process.env.NIGIWAI_E2E_REDIS ?? "redis://127.0.0.1:56379/0" });
  await client.connect();
  try {
    for await (const keys of client.scanIterator({ MATCH: "rl:*", COUNT: 200 })) {
      const batch = Array.isArray(keys) ? keys : [keys];
      if (batch.length) await client.del(batch);
    }
  } finally {
    await client.quit();
  }
}

export const uniqueEmail = (label: string) =>
  `${label}-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 6)}@example.com`;

/** Every page and state gets the same two checks: no console errors, and no failed requests. */
export function watch(page: Page) {
  const problems: string[] = [];
  page.on("console", (m) => {
    if (m.type() === "error") problems.push(`console: ${m.text()} @ ${m.location().url}`);
  });
  page.on("pageerror", (e) => problems.push(`pageerror: ${e.message}`));
  page.on("requestfailed", (r) => {
    const url = r.url();
    if (!url.includes("/_next/webpack-hmr")) problems.push(`requestfailed: ${r.method()} ${url} ${r.failure()?.errorText}`);
  });
  return problems;
}

export async function shot(page: Page, info: TestInfo, name: string, theme: "light" | "dark" = "light") {
  await page.waitForTimeout(450); // let colour transitions finish so the picture is what a person would see
  await page.screenshot({ path: `e2e-shots/${info.project.name}-${theme}-${name}.png`, fullPage: false });
}

export async function setTheme(page: Page, theme: "light" | "dark") {
  await page.evaluate((t) => document.documentElement.setAttribute("data-theme", t), theme);
}

export async function signUp(page: Page, business = "The Lantern"): Promise<{ email: string }> {
  const email = uniqueEmail("owner");
  await page.goto("/signup");
  await page.getByLabel("Venue or business name").fill(business);
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password", { exact: true }).fill(PASSWORD);
  await page.getByRole("button", { name: "Create account" }).click();
  await expect(page).toHaveURL(/\/app$/);
  return { email };
}

/** Sign an owner up through the API in an independent request context (its own cookie jar). */
export async function apiSignUp(request: APIRequestContext, business = "The Lantern") {
  const email = uniqueEmail("owner");
  const r = await request.post("/api/v1/auth/signup", { data: { email, password: PASSWORD, business_name: business } });
  expect(r.status()).toBe(201);
  return { email, me: await r.json() };
}

/** Build a published venue through the API with the request context's own session (so cookies and CSRF are real). */
export async function publishedVenue(
  request: APIRequestContext,
  opts: { reward?: { title: string; detail: string }; questions?: Record<string, unknown>; label?: string } = {},
): Promise<{ token: string; tenantId: string; businessId: string; qrId: string; email: string }> {
  const { email } = await apiSignUp(request);
  const me = await (await request.get("/api/v1/auth/me")).json();
  const headers = { "x-csrf-token": me.csrf_token };
  const t = `/api/v1/tenants/${me.tenants[0].id}`;
  const b = await (
    await request.post(`${t}/businesses`, { headers, data: { name: "The Lantern", type: "live_music_venue", currency: "GBP" } })
  ).json();
  const l = await (
    await request.post(`${t}/businesses/${b.id}/locations`, {
      headers,
      data: { name: "Main room", lat: 51.5, lon: -0.12, timezone: "Europe/London" },
    })
  ).json();
  const q = await (await request.post(`${t}/locations/${l.id}/qr-points`, { headers, data: { label: opts.label ?? "Bar end" } })).json();
  const s = await request.put(`${t}/businesses/${b.id}/survey`, {
    headers,
    data: { questions: opts.questions ?? {}, reward: opts.reward ?? null, publish: true },
  });
  expect(s.ok()).toBeTruthy();
  return { token: String(q.url).split("/").pop() as string, tenantId: me.tenants[0].id, businessId: b.id, qrId: q.id, email };
}
