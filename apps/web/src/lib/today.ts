import type { LabelKind } from "@/components/Label";

export type Evidence = { label: LabelKind; text: string; note: string | null };

export type FitGroup = { label: string; share: number; fit: number };

export type ActionFit = {
  soundcheck_id: string;
  score: number | null;
  band: [number, number] | null;
  provisional: boolean;
  groups: FitGroup[];
};

export type BoardAction = {
  key: string;
  kind: string;
  icon: "clock" | "music";
  title: string;
  why: string;
  evidence: Evidence[];
  fit: ActionFit | null;
  prov: string[];
  act: { name: string; entity_id: string; soundcheck_id: string | null } | null;
  decision: "accepted" | "dismissed" | null;
  logged: boolean;
};

export type QuietWindow = { weekday: number; start: number; end: number; scans: number; text: string };

export type Board = {
  week: string;
  generated_at: string;
  state: "day0" | "thin" | "ready";
  venue: { business: string; type: string; music: boolean };
  status: {
    scans: number;
    since: string | null;
    last_scan_days: number | null;
    basis: "guests" | "lineup" | null;
    unlock: { title: string; v: number; max: number; text: string } | null;
  };
  hours: {
    set: boolean;
    from: number | null;
    to: number | null;
    cells: (number | null)[][];
    scans_in_hours: number;
    early: boolean;
    picture: boolean;
    quiet: QuietWindow[];
  };
  actions: BoardAction[];
  hold: { title: string; scans: number; need: number; why: string; unlock: string[] } | null;
  notes: string[];
  labels: Record<string, LabelKind[]>;
};

export const WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"];
export const WEEKDAY_SHORT = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];

/** "since 3 September" from an ISO date, or null. */
export function sinceText(iso: string | null): string | null {
  if (!iso) return null;
  const d = new Date(`${iso}T12:00:00`);
  if (Number.isNaN(d.getTime())) return null;
  return d.toLocaleDateString("en-GB", { day: "numeric", month: "long" });
}

/** How long since the last scan, in words a person would say. */
export function lastScanText(days: number | null): string {
  if (days === null) return "none yet";
  if (days <= 0) return "today";
  if (days === 1) return "yesterday";
  return `${days} days ago`;
}
