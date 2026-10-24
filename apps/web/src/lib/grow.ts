/** Types for Grow (PRD M8), as the API returns them. */

export type GrowAct = { entity_id: string; name: string; genres: string[] };

export type Ghost = {
  group_index: number;
  tag_id: string;
  tag: string;
  bridges: string[];
  /** Guests (or acts) already carrying the genre; null when fewer than 10, which is never shown as a number. */
  carrying: number | null;
  unit: "guests" | "acts";
  neighbours_with_tag: number;
  acts: GrowAct[];
};

export type GhostSection = {
  status: "ok" | "none" | "not_group_specific";
  reason: string;
  unit: "guests" | "acts";
  act_similarity: number | null;
  groups_read: number[];
  skipped: { group_index: number; reason: string }[];
  limit: { similarity_max: number; absent_share: number; bridge_share: number; min_acts: number; min_group: number };
  items: Ghost[];
};

export type GrowPlace = {
  entity_id: string;
  name: string;
  distance_m: number | null;
  address: string | null;
  lat: number | null;
  lon: number | null;
};

export type PlaceGroup = { group_index: number; group: string; items: GrowPlace[]; own: boolean };

export type PlaceSection = {
  label: string;
  status: "ok" | "empty";
  mode: "taste" | "near" | null;
  crowd_size: number;
  seed_effect: number | null;
  similarity: number | null;
  told_apart: boolean;
  items: GrowPlace[];
  by_group: PlaceGroup[] | null;
  limit: { seed_effect_min: number; similarity_max: number };
  note: string;
  gaps?: { group_index: number; group: string }[];
};

export type PlacesPart =
  | { status: "unavailable"; reason: string }
  | {
      status: "ok";
      category: string | null;
      radius_m: number;
      wide_radius_m: number;
      nearby: PlaceSection;
      elsewhere: PlaceSection;
      dropped_closed: number;
      closure_unanswered: boolean;
    };

export type GrowRun = {
  basis: { kind: "guests" | "lineup"; ref: string; label: string; provisional: boolean };
  groups: { index: number; label: string; share: number }[];
  ghosts: GhostSection;
  places: PlacesPart;
  trace_ids: string[];
  generated_at: string;
};

export type GrowState = "no_crowd" | "not_run" | "queued" | "running" | "failed" | "stale" | "ready";

export type GrowDoc = {
  state: GrowState;
  reason: string;
  can_build: boolean;
  basis_now: { kind: "guests" | "lineup" | null; ref: string | null };
  run: GrowRun | null;
  updated_at: string | null;
  error: string | null;
};

export type GrowCall = {
  id: string;
  at: string;
  purpose: string;
  endpoint: string;
  params: [string, string][];
  status: string;
  transport: string;
  cache: string;
  latency_ms: number;
  results: number;
};

export function metres(m: number | null): string {
  if (m === null) return "";
  return m >= 1000 ? `${(m / 1000).toFixed(1)} km` : `${m} m`;
}

export function percent(x: number | null): string {
  return x === null ? "n/a" : `${Math.round(x * 100)}%`;
}
