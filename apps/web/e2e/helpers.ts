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
    while (chosen.length < 5) {
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

/** An artist Qloo "knows" for the tests that must not call Qloo: stored with its tags, so Soundcheck can load it. */
export async function plantArtist(name: string, genres: string[]): Promise<string> {
  const id = randomUUID();
  const tags = genres.map((g) => [`urn:tag:genre:qloo:${g.toLowerCase().replace(/\W+/g, "_")}`, g, "urn:tag:genre:qloo"]);
  await sql(
    "INSERT INTO qloo_entity (entity_id, type, types, name_nfc, tags, popularity, insights_eligible) VALUES ($1, 'urn:entity:artist', ARRAY['urn:entity:artist'], $2, $3::jsonb, 0.2, true)",
    [id, name, JSON.stringify(tags)],
  );
  return id;
}

/** A ready public-lineup profile whose acts are three genre scenes, stored with their tags (no Qloo call involved). */
export async function plantLineup(tenantId: string, businessId: string, opts: { events: number; place?: string }): Promise<void> {
  const scenes = [
    ["Indie rock", "Post-punk", "Shoegaze", "Garage rock", "Lo-fi"],
    ["Jazz", "Bebop", "Swing", "Big band", "Cool jazz"],
    ["Techno", "House", "Ambient", "Minimal", "Electro"],
  ];
  const tag = Date.now().toString(36);
  const acts: unknown[] = [];
  for (let g = 0; g < scenes.length; g++) {
    for (let i = 0; i < 9; i++) {
      const id = randomUUID();
      const tags = [0, 1, 2].map((k) => {
        const name = scenes[g]![(i + k) % 5]!;
        return [`urn:tag:genre:qloo:${name.toLowerCase().replace(/\W+/g, "_")}`, name, "urn:tag:genre:qloo"];
      });
      await sql(
        "INSERT INTO qloo_entity (entity_id, type, types, name_nfc, tags, insights_eligible) VALUES ($1, 'urn:entity:artist', ARRAY['urn:entity:artist'], $2, $3::jsonb, true)",
        [id, `Scene ${g} Act ${i} ${tag}`, JSON.stringify(tags)],
      );
      acts.push({ entity_id: id, name: `Scene ${g} Act ${i} ${tag}`, mbid: randomUUID(), events: 2 + (i % 5) + (g === 0 ? 6 : 0), tags });
    }
  }
  const doc = {
    state: "profile",
    events: { used: opts.events, with_lineup: opts.events },
    performers: { unique: acts.length + 5, resolved: acts.length },
    weekdays: [0, 0, 1, 2, 12, 20, 5],
    acts,
  };
  await sql(
    "INSERT INTO lineup_profile (tenant_id, business_id, place_mbid, place_name, status, result, finished_at) VALUES ($1, $2, $3, $4, 'ready', $5::jsonb, now())",
    [tenantId, businessId, randomUUID(), opts.place ?? "Mercury Test Room", JSON.stringify(doc)],
  );
}

/** Open every day 12:00 to 23:00, so the Today board can tell a quiet hour from a closed one. */
export async function openAllWeek(businessId: string): Promise<void> {
  const week = Array.from({ length: 7 }, () => ({ open: "12:00", close: "23:00" }));
  await sql("UPDATE location SET hours = $1::jsonb WHERE business_id = $2", [JSON.stringify(week), businessId]);
}

/** Give the 90 planted responses of a venue an exact week: one scan in every open hour from 12:00 to 22:00, none on
 * Wednesday 14:00 to 17:00, and a busy Friday evening and Saturday 19:00. */
export async function setRhythm(qrId: string): Promise<void> {
  const cells: [number, number][] = [];
  for (let day = 0; day < 7; day++) {
    for (let hour = 12; hour < 23; hour++) {
      let n = 1;
      if (day === 2 && hour >= 14 && hour <= 16) n = 0;
      if (day === 4 && hour >= 18 && hour <= 20) n += 4;
      if (day === 5 && hour === 19) n += 4;
      for (let i = 0; i < n; i++) cells.push([day, hour]);
    }
  }
  const ids = (await sql<{ id: string }>("SELECT id FROM response WHERE qr_point_id = $1 ORDER BY id", [qrId])).rows.map((r) => r.id);
  if (ids.length !== cells.length) throw new Error(`plant ${cells.length} responses, found ${ids.length}`);
  for (let i = 0; i < ids.length; i++) {
    await sql("UPDATE response SET local_weekday = $1, local_hour = $2 WHERE id = $3", [cells[i]![0], cells[i]![1], ids[i]]);
  }
}

/** Suggested acts and their stored Soundchecks for a venue read from public lineups, as the worker would leave them. */
export async function plantSuggestions(tenantId: string, businessId: string, acts: { name: string; score: number; best: string }[]): Promise<void> {
  const ref = (
    await sql<{ ref: string }>(
      `SELECT to_char(finished_at AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US"+00:00"') AS ref FROM lineup_profile WHERE business_id = $1`,
      [businessId],
    )
  ).rows[0]?.ref;
  if (!ref) throw new Error("plant a lineup first");
  const top: unknown[] = [];
  for (const a of acts) {
    const entity = randomUUID();
    const band = [a.score - 5, Math.min(100, a.score + 4)];
    const result = {
      status: "ok",
      score: a.score,
      band,
      provisional: true,
      groups: [
        { index: 0, label: "Indie rock acts", share: 0.55, fit: 0.93, status: "scored" },
        { index: 1, label: "Jazz acts", share: 0.3, fit: 0.71, status: "scored" },
        { index: 2, label: "Techno acts", share: 0.15, fit: 0.3, status: "scored" },
      ],
    };
    const row = await sql<{ id: string }>(
      "INSERT INTO soundcheck (tenant_id, business_id, candidate_entity_id, candidate_name, basis_kind, basis_ref, input_hash, weights_version, result) VALUES ($1, $2, $3, $4, 'lineup', $5, $6, 'v0', $7::jsonb) RETURNING id",
      [tenantId, businessId, entity, a.name, ref, randomUUID(), JSON.stringify(result)],
    );
    top.push({ soundcheck_id: row.rows[0]!.id, entity_id: entity, name: a.name, score: a.score, band, best_for: a.best, provisional: true });
  }
  const doc = { basis: { kind: "lineup", ref, label: "public lineups" }, considered: acts.length, scored: acts.length, top, wildcard: null, generated_at: new Date().toISOString() };
  await sql(
    "INSERT INTO act_suggestion (business_id, tenant_id, status, basis_kind, basis_ref, result) VALUES ($1, $2, 'ready', 'lineup', $3, $4::jsonb) ON CONFLICT (business_id) DO UPDATE SET status = 'ready', basis_kind = 'lineup', basis_ref = EXCLUDED.basis_ref, result = EXCLUDED.result",
    [businessId, tenantId, ref, JSON.stringify(doc)],
  );
}
