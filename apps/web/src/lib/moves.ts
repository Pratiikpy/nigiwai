/** Types for Moves and their results (PRD M11, M20), as the API returns them. */

export type MoveKind = "act" | "event" | "menu" | "ad" | "price" | "other";

export const KIND_LABELS: Record<MoveKind, string> = {
  act: "Act booked",
  event: "Event",
  menu: "Menu or product",
  ad: "Ad run",
  price: "Price change",
  other: "Something else",
};

export type Verdict = "more" | "fewer" | "inconclusive" | "too_early";

export const VERDICT_LABELS: Record<Verdict, string> = {
  more: "More scans",
  fewer: "Fewer scans",
  inconclusive: "Inconclusive",
  too_early: "Too early to say",
};

export type Mix = { scans: number; shown: boolean; groups: { label: string; share: number }[] };

export type MoveResult = {
  slot: string;
  before: { from: string; to: string; days: number; scans: number };
  after: { from: string; to: string | null; days: number; scans: number };
  interval: string;
  rate: { before: number; after: number; ratio: number | null; low: number | null; high: number | null; p: number | null } | null;
  verdict: Verdict;
  text: string;
  mix: { before: Mix; after: Mix } | null;
};

export type Move = {
  id: string;
  kind: MoveKind;
  title: string;
  started_on: string;
  ended_on: string | null;
  source: "today" | "manual";
  note: string | null;
  slot: { weekdays: number[]; from: number | null; to: number | null; text: string };
  result: MoveResult;
};

export type MovesDoc = {
  today: string;
  weeks: number;
  moves: Move[];
  ledger: { moves: number; kinds: { kind: MoveKind; moves: number; more: number; fewer: number; inconclusive: number; waiting: number }[] };
};

export type MoveForm = {
  kind: MoveKind;
  title: string;
  started_on: string;
  ended_on: string;
  weekdays: number[];
  allHours: boolean;
  hour_from: number;
  hour_to: number;
  note: string;
};

export const hourLabel = (h: number) => `${String(h % 24).padStart(2, "0")}:00`;

/** The request body for a form, or the first thing wrong with it in words. */
export function moveBody(f: MoveForm): { body: Record<string, unknown> } | { problem: string } {
  const title = f.title.trim();
  if (!title) return { problem: "Say what changed." };
  if (!f.started_on) return { problem: "Choose the day it started." };
  if (f.ended_on && f.ended_on < f.started_on) return { problem: "The end date cannot be before the start date." };
  if (!f.allHours && f.hour_from >= f.hour_to) return { problem: "The slot must end after it starts." };
  return {
    body: {
      kind: f.kind,
      title,
      started_on: f.started_on,
      ended_on: f.ended_on || null,
      weekdays: [...f.weekdays].sort(),
      hour_from: f.allHours ? null : f.hour_from,
      hour_to: f.allHours ? null : f.hour_to,
      note: f.note.trim() || null,
    },
  };
}

export const emptyForm = (today: string): MoveForm => ({
  kind: "act",
  title: "",
  started_on: today,
  ended_on: "",
  weekdays: [],
  allHours: true,
  hour_from: 18,
  hour_to: 22,
  note: "",
});

export const formOf = (m: Move): MoveForm => ({
  kind: m.kind,
  title: m.title,
  started_on: m.started_on,
  ended_on: m.ended_on ?? "",
  weekdays: m.slot.weekdays,
  allHours: m.slot.from === null || m.slot.to === null,
  hour_from: m.slot.from ?? 18,
  hour_to: m.slot.to ?? 22,
  note: m.note ?? "",
});
