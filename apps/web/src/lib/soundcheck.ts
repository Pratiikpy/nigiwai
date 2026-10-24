// What the Soundcheck endpoints return (apps/api/src/nigiwai_api/routers/soundcheck.py).

export type BasisStatus = {
  guests: { state: string; version: number; n: number; groups: number; usable: boolean } | null;
  lineup: {
    status: string;
    place: string;
    events: number;
    acts: number;
    sufficient: boolean;
    needs_refresh: boolean;
    usable: boolean;
  } | null;
  use: "guests" | "lineup" | null;
};

export type ActHit = {
  entity_id: string;
  name: string;
  type: string;
  year: number | null;
  description: string | null;
};
export type ActSearch = { items: ActHit[]; source: string; message: string | null };

export type GroupFit = {
  index: number;
  label: string;
  share: number;
  size: number;
  status: "scored" | "no_affinity" | "too_few_references";
  fit: number | null;
  references: number;
  candidate_affinity: number | null;
  alone: number | null;
};

export type Constraint = { name: string; status: "pass" | "fail" | "not_scored"; detail: string };

export type Verdict = {
  id: string;
  created_at: string;
  status: "ok" | "insufficient" | "fails_constraint" | "unscored";
  reason: string;
  provisional: boolean;
  score: number | null;
  band: [number, number] | null;
  groups: GroupFit[];
  components: { group_fit: number | null; peer: number | null; risk: number | null };
  weights: Record<string, unknown>;
  weights_version: string;
  peer_used: boolean;
  formula: string;
  constraints: Constraint[];
  why: string[];
  watch: string[];
  nights: number[] | null;
  suits: number[];
  notes: string[];
  input_hash: string;
  crowd: { kind: "guests" | "lineup"; n: number };
  candidate: {
    entity_id: string;
    name: string;
    genres: string[];
    description: string | null;
    year: number | null;
    popularity: number | null;
  };
  basis: {
    kind: "guests" | "lineup";
    ref: string;
    label: string;
    groups: { index: number; label: string; share: number; size: number; seeds: string[] }[];
  };
  played_here: number | null;
  problems: string[];
};

export type Suggested = {
  soundcheck_id: string;
  entity_id: string;
  name: string;
  genres: string[];
  popularity: number | null;
  score: number;
  band: [number, number];
  best_for: string | null;
  watch: string | null;
  suits: number[];
  provisional: boolean;
};

export type Suggestions = {
  status: "queued" | "running" | "ready" | "failed";
  error: string | null;
  updated_at: string;
  result: {
    basis: { kind: string; ref: string; label: string };
    considered: number;
    scored: number;
    top: Suggested[];
    wildcard: Suggested | null;
    generated_at: string;
  } | null;
} | null;

export type QlooCall = {
  id: string;
  at: string;
  purpose: string;
  endpoint: string;
  params: [string, string][];
  status: string;
  http_status: number | null;
  transport: string;
  cache: string;
  latency_ms: number;
  results: number;
  rules: { rule: string; effect: string; detail: string }[];
};

export type Recent = {
  id: string;
  entity_id: string;
  name: string;
  basis: string;
  status: string;
  score: number | null;
  band: [number, number] | null;
  created_at: string;
}[];

export const WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"];
export const WEEKDAY_INITIAL = ["M", "T", "W", "T", "F", "S", "S"];

/** "Friday and Saturday", "Friday, Saturday and Sunday". */
export function dayList(days: number[]): string {
  const names = days.map((d) => WEEKDAYS[d] ?? "");
  if (names.length <= 1) return names.join("");
  return `${names.slice(0, -1).join(", ")} and ${names[names.length - 1]}`;
}
