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

export async function signIn(page: Page, email: string): Promise<void> {
  await page.goto("/login");
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password", { exact: true }).fill(PASSWORD);
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page).toHaveURL(/\/app$/);
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

function rng(seed: number) {
  // mulberry32: small, seedable, good enough to plant a crowd
  let a = seed >>> 0;
  return () => {
    a = (a + 0x6d2b79f5) >>> 0;
    let t = a;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

const KINDS = ["artist", "movie", "brand"];

/** Put n invented guests, drawn from three planted taste groups, into a business through the same database function the
 * survey uses. Each item carries tags mostly from its own group's pool, as Qloo's tags would. Returns nothing: the
 * point is what the product makes of them. */
export async function plantCrowd(businessId: string, qrId: string, n: number, seed = 1): Promise<void> {
  const r = rng(seed);
  const tag = `${seed}x${Date.now().toString(36)}`;
  const survey = (await sql<{ id: string; version: number }>(
    "SELECT id, version FROM survey WHERE business_id = $1 AND status = 'published'",
    [businessId],
  )).rows[0];
  if (!survey) throw new Error("no published survey");
  const groups: { id: string; urn: string }[][] = [];
  for (let t = 0; t < 3; t++) {
    const group: { id: string; urn: string }[] = [];
    for (let e = 0; e < 24; e++) {
      const urn = `urn:entity:${KINDS[e % 3]}`;
      const id = randomUUID();
      const own = new Set<number>();
      while (own.size < 4) own.add(Math.floor(r() * 14));
      const tags = [...own].map((j) => [`urn:tag:genre:qloo:${tag}t${t}_${j}`, `Flavour ${t}-${j}`, "urn:tag:genre:qloo"]);
      tags.push([`urn:tag:genre:qloo:${tag}generic${Math.floor(r() * 3)}`, "Generic", "urn:tag:genre:qloo"]);
      tags.push([`urn:tag:style:qloo:${tag}noise${Math.floor(r() * 30)}`, "Noise", "urn:tag:style:qloo"]);
      await sql(
        "INSERT INTO qloo_entity (entity_id, type, types, name_nfc, tags, insights_eligible) VALUES ($1, $2, $3, $4, $5::jsonb, true)",
        [id, urn, [urn], `Planted ${t}-${e} ${tag}`, JSON.stringify(tags)],
      );
      group.push({ id, urn });
    }
    groups.push(group);
  }
  const flat = groups.flat();
  for (let i = 0; i < n; i++) {
    const t = Math.floor(r() * 3);
    const chosen: { id: string; urn: string }[] = [];
    while (chosen.length < 5) {
      const pick = r() < 0.85 ? groups[t]![Math.floor(r() * 24)]! : flat[Math.floor(r() * flat.length)]!;
      if (!chosen.includes(pick)) chosen.push(pick);
    }
    await sql("SELECT public_insert_response($1, $2, $3, 'v1', NULL, NULL, NULL, 'ok', $4, $5, $6)", [
      qrId,
      survey.id,
      survey.version,
      chosen.map((c) => c.id),
      chosen.map((c) => c.urn),
      Buffer.from(randomUUID().replace(/-/g, ""), "hex"),
    ]);
  }
  await sql(
    "UPDATE response SET local_weekday = floor(random() * 7)::int, local_hour = floor(random() * 24)::int WHERE qr_point_id = $1",
    [qrId],
  );
}

/** Plant responses from crowds of real items (ids that Qloo returned), three picks or more each, spread over the crowds. */
export async function plantRealCrowds(
  qrId: string,
  businessId: string,
  crowds: { id: string; urn: string }[][],
  n: number,
  seed = 1,
): Promise<void> {
  const r = rng(seed);
  const survey = (await sql<{ id: string; version: number }>(
    "SELECT id, version FROM survey WHERE business_id = $1 AND status = 'published'",
    [businessId],
  )).rows[0];
  if (!survey) throw new Error("no published survey");
  for (let i = 0; i < n; i++) {
    const group = crowds[i % crowds.length]!;
    const chosen: { id: string; urn: string }[] = [];
    while (chosen.length < 4) {
      const pick = group[Math.floor(r() * group.length)]!;
      if (!chosen.includes(pick)) chosen.push(pick);
    }
    await sql("SELECT public_insert_response($1, $2, $3, 'v1', NULL, NULL, NULL, 'ok', $4, $5, $6)", [
      qrId,
      survey.id,
      survey.version,
      chosen.map((c) => c.id),
      chosen.map((c) => c.urn),
      Buffer.from(randomUUID().replace(/-/g, ""), "hex"),
    ]);
  }
  await sql(
    "UPDATE response SET local_weekday = floor(random() * 7)::int, local_hour = floor(random() * 24)::int WHERE qr_point_id = $1",
    [qrId],
  );
}
