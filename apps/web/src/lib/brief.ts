// The Booking Brief document (apps/api/src/nigiwai_api/services/brief.py): item names, up to three genre labels for each act and our own scores only.

export type BriefAct = {
  name: string;
  genres: string[];
  score: number;
  band: [number, number];
  best_for: string | null;
  watch: string | null;
  groups: { label: string; fit: number }[];
  provisional: boolean;
};

export type Brief = {
  title: string;
  venue: { business: string; place: string | null };
  date: string;
  status: "ok" | "thin";
  reason: string;
  basis: { kind: "guests" | "lineup"; label: string; provisional: boolean; n: number; unit: "guests" | "events" } | null;
  groups: { label: string; share: number; size: number; when: string | null }[];
  acts: BriefAct[];
  wildcard: BriefAct | null;
  nights: { days: number[]; text: string } | null;
  notes: string[];
  labels: Record<string, ("measured" | "observed" | "modelled")[]>;
  how: string;
  expires_at?: string;
};

export type Share = { id: string; created_at: string; expires_at: string; live: boolean };

export const longDate = (iso: string) => {
  const d = new Date(`${iso}T12:00:00`);
  return `${d.getDate()} ${d.toLocaleString("en-GB", { month: "long" })}`;
};
