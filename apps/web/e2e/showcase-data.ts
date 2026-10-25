import { randomUUID } from "node:crypto";
import { expect } from "@playwright/test";
import { openAllWeek, sql } from "./helpers";

// A made-up room with made-up guests, for the screenshots in docs/screenshots. Every act, film and brand below is invented (and chosen to
// sound like nothing in particular); the genres are ordinary words. The point is a workspace that reads like a real one, with no Qloo data
// in it: the guests are planted through the same database function the survey uses, and the groups, the board, the map and the plan are
// then made from them by the product itself.

type Scene = { name: string; genres: string[]; acts: string[]; films: string[]; brands: string[] };

export const SCENES: Scene[] = [
  {
    name: "indie and folk",
    genres: ["Indie folk", "Dream pop", "Shoegaze", "Lo-fi", "Chamber pop", "Slowcore", "Bedroom pop", "Folk rock"],
    acts: ["Marlowe and the Tide", "Paper Lanterns", "Hollow Pines", "Saltwater Choir", "Juniper Hours", "Quiet Harbour", "The Moth Season", "Little Orchard"],
    films: ["The Orchard Keeper", "Slow Tides", "Letters from Marrow", "A Quiet Season", "The Paper Boat", "Winter at Kestrel Bay", "Small Hours", "Fern Hill"],
    brands: ["Wren and Alder", "Mossgate Press", "Halcyon Tea Co.", "Linen Row", "Kettle and Fern", "Oakhand Books", "Bluebell Mill", "Thistle Post"],
  },
  {
    name: "loud and fast",
    genres: ["Punk", "Garage rock", "Hardcore", "Noise rock", "Post-punk", "Skate punk", "Surf punk", "Grunge"],
    acts: ["Rust Engine", "Bad Weather Club", "Static Hymns", "The Fuse Kids", "Concrete Valentine", "Nine Volt Saints", "Sunday Wrecking Crew", "Burnt Orange Riot"],
    films: ["Concrete Summer", "Last Bus to Tilbury", "Feedback", "Broken Amplifier", "The Long Weekend War", "Scrapyard Kings", "Third Rail", "Loud Neighbours"],
    brands: ["Ironmonger Denim", "Black Anchor Gear", "Volt and Vinyl", "Crowbar Coffee", "Kickdrum Skate", "Switchblade Tees", "Tarmac Boots", "Grease and Glory"],
  },
  {
    name: "jazz and soul",
    genres: ["Jazz", "Soul", "Blues", "Bossa nova", "Neo-soul", "Funk", "Bebop", "Swing"],
    acts: ["Velvet Quartet", "Amber Room Trio", "Midnight Meridian", "The Copper Sextet", "Sunday Brass", "Blue Lantern Orchestra", "Harbour Lights Five", "Marigold Ensemble"],
    films: ["Blue Hour in Lisbon", "The Last Set", "Smoke and Satin", "After Midnight Avenue", "A Quiet Piano", "Velvet Rooms", "The Saxophone Summer", "Nocturne for Two"],
    brands: ["Ruby Lane Records", "Gilt and Grain", "Cedar and Silk", "Bottle and Brass", "Tailored Hours", "Nightcap Spirits", "Mercer Vinyl", "Copperfield Hats"],
  },
];

const KINDS = ["artist", "movie", "brand"] as const;

function rng(seed: number) {
  let a = seed >>> 0;
  return () => {
    a = (a + 0x6d2b79f5) >>> 0;
    let t = a;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

type Item = { id: string; urn: string; name: string; scene: number };

/** The invented items of every scene, stored as Qloo's index would hold them (with tags), and the guests who picked among them. */
export async function plantShowcaseCrowd(businessId: string, qrId: string, guests: number, seed = 5): Promise<Item[][]> {
  const r = rng(seed);
  const survey = (await sql<{ id: string; version: number }>("SELECT id, version FROM survey WHERE business_id = $1 AND status = 'published'", [businessId])).rows[0];
  if (!survey) throw new Error("no published survey");
  // an earlier run left the same names behind: they stop being offered by the picker, so a search shows each one once
  await sql("UPDATE qloo_entity SET insights_eligible = false WHERE tags::text LIKE '%showcase\\_%'");
  const scenes: Item[][] = [];
  for (const [s, scene] of SCENES.entries()) {
    const items: Item[] = [];
    for (const [k, kind] of KINDS.entries()) {
      const names = [scene.acts, scene.films, scene.brands][k]!;
      for (const name of names) {
        const urn = `urn:entity:${kind}`;
        const id = randomUUID();
        const own = new Set<number>();
        while (own.size < 4) own.add(Math.floor(r() * scene.genres.length));
        // the tag ids are the same on every run, so a second run's items (same names, same tags) group with the first's and nothing is renamed
        const tags = [...own].map((j) => [`urn:tag:genre:qloo:showcase_${s}_${j}`, scene.genres[j]!, "urn:tag:genre:qloo"]);
        const style = Math.floor(r() * 3);
        tags.push([`urn:tag:style:qloo:showcase_${["acclaimed", "cult", "classic"][style]}`, ["Acclaimed", "Cult", "Classic"][style]!, "urn:tag:style:qloo"]);
        await sql("INSERT INTO qloo_entity (entity_id, type, types, name_nfc, tags, insights_eligible) VALUES ($1, $2, $3, $4, $5::jsonb, true)", [id, urn, [urn], name, JSON.stringify(tags)]);
        items.push({ id, urn, name, scene: s });
      }
    }
    scenes.push(items);
  }
  const flat = scenes.flat();
  for (let i = 0; i < guests; i++) {
    const s = Math.floor(r() * 3);
    const chosen: Item[] = [];
    while (chosen.length < 5) {
      const pick = r() < 0.88 ? scenes[s]![Math.floor(r() * scenes[s]!.length)]! : flat[Math.floor(r() * flat.length)]!;
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
  await weekOfScans(qrId, guests);
  return scenes;
}

/** A believable week of scans for a room open 12:00 to 23:00: busy Thursday to Saturday evenings, nothing on a Wednesday afternoon. */
async function weekOfScans(qrId: string, guests: number): Promise<void> {
  const cells: [number, number][] = [];
  const add = (day: number, hour: number, n: number) => {
    for (let i = 0; i < n; i++) cells.push([day, hour]);
  };
  for (let day = 0; day < 7; day++) {
    for (let hour = 12; hour < 23; hour++) {
      let n = 2;
      if (day === 2 && hour >= 14 && hour <= 16) n = 0;
      if (day === 3 && hour >= 19 && hour <= 21) n += 3;
      if (day === 4 && hour >= 18 && hour <= 21) n += 7;
      if (day === 5 && hour >= 17 && hour <= 21) n += 6;
      if (day === 6 && hour >= 13 && hour <= 16) n += 1;
      add(day, hour, n);
    }
  }
  // land on exactly the number of guests: trim from the quietest hours' extra scans, or add to the busiest evening
  while (cells.length > guests) cells.pop();
  while (cells.length < guests) cells.push([4, 19]);
  const ids = (await sql<{ id: string }>("SELECT id FROM response WHERE qr_point_id = $1 ORDER BY id", [qrId])).rows.map((x) => x.id);
  expect(ids).toHaveLength(cells.length);
  for (const [i, id] of ids.entries()) {
    await sql("UPDATE response SET local_weekday = $1, local_hour = $2 WHERE id = $3", [cells[i]![0], cells[i]![1], id]);
  }
}

/** Wait until the worker has fitted the groups. */
export async function fittedShowcase(businessId: string): Promise<{ version: number; shown: { index: number; label: string; share: number }[] }> {
  await sql("UPDATE job SET run_after = now() WHERE business_id = $1", [businessId]);
  await expect
    .poll(async () => (await sql("SELECT state FROM tribe_version WHERE business_id = $1 ORDER BY version DESC LIMIT 1", [businessId])).rows[0]?.state, { timeout: 180_000 })
    .toMatch(/provisional|named/);
  const latest = (
    await sql<{ version: number; result: { tribes: { index: number; label: string; share: number; shown?: boolean }[] } }>(
      "SELECT version, result FROM tribe_version WHERE business_id = $1 ORDER BY version DESC LIMIT 1",
      [businessId],
    )
  ).rows[0]!;
  return { version: latest.version, shown: latest.result.tribes.filter((t) => t.shown).map((t) => ({ index: t.index, label: t.label, share: t.share })) };
}

/** Acts for the room, scored the way a suggestion run leaves them: each best for one group, a Soundcheck stored for the top three, and a
 * scored pool for the Sound plan. Names are invented. */
export async function plantShowcaseActs(tenantId: string, businessId: string, groups: { index: number; label: string; share: number }[], version: number): Promise<void> {
  const acts = [
    { name: "Juniper Hours and the Slow Tide", genres: ["indie folk", "dream pop"] },
    { name: "Copper Lantern Quartet", genres: ["jazz", "soul"] },
    { name: "Static Orchard", genres: ["shoegaze", "lo-fi"] },
    { name: "The Midnight Marigolds", genres: ["neo-soul", "funk"] },
    { name: "Harbour Wrecking Club", genres: ["punk", "garage rock"] },
    { name: "Little Brass Society", genres: ["swing", "bebop"] },
    { name: "Velvet Anchor", genres: ["slowcore", "chamber pop"] },
    { name: "Nine Volt Parade", genres: ["post-punk", "noise rock"] },
  ];
  const fitsFor = (i: number) => {
    const fits: Record<string, number> = {};
    groups.forEach((g, j) => {
      fits[String(g.index)] = j === i % groups.length ? 0.97 - 0.015 * Math.floor(i / groups.length) : 0.28 + 0.07 * ((i + j) % 4);
    });
    return fits;
  };
  const scoreOf = (i: number) => 94 - 3 * i;
  const top: unknown[] = [];
  for (const [i, a] of acts.slice(0, 3).entries()) {
    const entity = randomUUID();
    const score = scoreOf(i);
    const band = [score - 4, Math.min(100, score + 3)];
    const fits = fitsFor(i);
    const result = {
      status: "ok",
      score,
      band,
      provisional: false,
      groups: groups.map((g) => ({ index: g.index, label: g.label, share: g.share, fit: fits[String(g.index)], status: "scored" })),
      nights: [0.2, 0.3, 0.35, 0.8, 1, 0.95, 0.5], // Monday to Sunday: how the act's groups come
    };
    const row = await sql<{ id: string }>(
      "INSERT INTO soundcheck (tenant_id, business_id, candidate_entity_id, candidate_name, basis_kind, basis_ref, input_hash, weights_version, result) VALUES ($1, $2, $3, $4, 'guests', $5, $6, 'v0', $7::jsonb) RETURNING id",
      [tenantId, businessId, entity, a.name, String(version), randomUUID(), JSON.stringify(result)],
    );
    top.push({ soundcheck_id: row.rows[0]!.id, entity_id: entity, name: a.name, score, band, best_for: groups[i % groups.length]!.label, watch: "Nothing stands out.", provisional: false, genres: a.genres });
  }
  const pool = acts.map((a, i) => ({ entity_id: randomUUID(), name: a.name, genres: a.genres, popularity: 0.3, score: scoreOf(i), fits: fitsFor(i) }));
  const doc = { basis: { kind: "guests", ref: String(version), label: "your guests" }, considered: acts.length, scored: acts.length, top, wildcard: null, pool, generated_at: new Date().toISOString() };
  await sql(
    "INSERT INTO act_suggestion (business_id, tenant_id, status, basis_kind, basis_ref, result) VALUES ($1, $2, 'ready', 'guests', $3, $4::jsonb) ON CONFLICT (business_id) DO UPDATE SET status = 'ready', basis_kind = 'guests', basis_ref = EXCLUDED.basis_ref, result = EXCLUDED.result",
    [businessId, tenantId, String(version), JSON.stringify(doc)],
  );
}

export { openAllWeek };
