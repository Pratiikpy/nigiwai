/** The tribe result as the owner's browser receives it (the fitted profiles stay on the server). */
export type TagLift = { tag_id: string; name: string; lift: number; lo: number; hi: number; support: number };
export type TopItem = { entity_id: string; name: string; type: string; weight: number };
export type Signature = {
  types: [string, string];
  tribe_share: number;
  crowd_share: number;
  lift: number;
  q: number;
  group_size: number;
  odd: boolean;
};
export type TribeCard = {
  index: number;
  name: string | null;
  label: string;
  line: string;
  soft_size: number;
  share: number;
  shown: boolean;
  top_tags: TagLift[];
  top_items: TopItem[];
  used_tags: string[];
  signatures: Signature[];
  rhythm: number[][];
  tag_overlap: number | null;
};
export type Stability = {
  raw: number;
  null_permuted: number;
  null_random_picks: number;
  corrected: number;
  p_permuted: number;
  p_random_picks: number;
  null_runs: number;
  ref_ari: number;
  tag_overlap: number[];
  ref_sizes: number[];
  bootstrap: number;
  beats_both_nulls: boolean;
};
export type AudienceReading =
  | {
      status: "ok";
      items_asked: number;
      items_used: number;
      age: { index: number; band: "younger" | "mixed" | "older"; label: string };
      gender: { index: number; band: "women" | "balanced" | "men"; label: string };
    }
  | { status: "thin"; items_asked: number; items_used: number; reason: string }
  | { status: "unavailable"; reason: string };
export type TribeResult = {
  version: number;
  state: "none" | "unstable" | "provisional" | "named";
  reason: string;
  n: number;
  k: number;
  input_hash: string;
  stability: Stability | null;
  vocab_size: number;
  tribes: TribeCard[];
  crowd_rhythm: number[][];
  timed: number;
  dropped: Record<string, number>;
  audience?: Record<string, AudienceReading>;
  meta?: { responses: number; computed_at: string };
};
export type TribesPayload = {
  responses: number;
  unlock: { provisional: number; named: number; min_group: number };
  refit_queued: boolean;
  version: number | null;
  computed_at: string | null;
  result: TribeResult | null;
};

export const DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
export const PARTS = [
  { label: "Morning", hint: "6 to 11", hours: [6, 7, 8, 9, 10, 11] },
  { label: "Afternoon", hint: "12 to 16", hours: [12, 13, 14, 15, 16] },
  { label: "Evening", hint: "17 to 21", hours: [17, 18, 19, 20, 21] },
  { label: "Late", hint: "22 to 5", hours: [22, 23, 0, 1, 2, 3, 4, 5] },
];

/** 7 weekdays by 4 parts of the day, from the 7 by 24 grid. */
export function byDaypart(grid: number[][]): number[][] {
  return DAYS.map((_, d) => PARTS.map((p) => p.hours.reduce((sum, h) => sum + (grid[d]?.[h] ?? 0), 0)));
}

export const TRIBE_COLOURS = ["var(--t1)", "var(--t2)", "var(--t3)", "var(--tu)", "var(--accent)"];

export function typeWord(type: string): string {
  const key = type.split(":").pop() ?? type;
  return (
    { artist: "Music", movie: "Film", tv_show: "Show", brand: "Brand", book: "Book", podcast: "Podcast", videogame: "Game" }[key] ??
    key
  );
}

export function liftText(t: TagLift): string {
  return `${t.lift.toFixed(1)}× (${t.lo.toFixed(1)} to ${t.hi.toFixed(1)})`;
}
