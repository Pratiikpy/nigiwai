/** Types for the Sound plan (PRD M26), as the API returns it. */

export type SoundAct = {
  entity_id: string;
  name: string;
  genres: string[];
  score: number;
  best_for: string;
  best_share?: number;
  best_rank?: number;
};

export type SoundCell = {
  key: string;
  days: string;
  part: string;
  hours: string;
  status: "ok" | "thin" | "closed";
  reason: string | null;
  scans: number;
  busy: number | null;
  busy_label: "busy" | "steady" | "quiet" | null;
  mix: { index: number; label: string; share: number }[];
  acts: SoundAct[];
};

export type SoundPlan = {
  state: "ready" | "no_crowd" | "needs_acts" | "stale";
  reason: string | null;
  can_build?: boolean;
  kind?: "timed" | "undated";
  has_hours?: boolean;
  basis?: { kind: "guests" | "lineup"; label: string; provisional: boolean };
  business_type?: string;
  acts_updated_at?: string;
  notes: string[];
  plan: null | {
    version: string;
    formula: string;
    acts_considered: number;
    cells?: SoundCell[];
    acts?: SoundAct[];
  };
};

/** The plan as plain text, for pasting into a note or a message to whoever plays the music. */
export function planText(doc: SoundPlan): string {
  const lines: string[] = ["Sound plan", doc.basis ? `Based on: ${doc.basis.label}${doc.basis.provisional ? " (provisional)" : ""}` : "", ""];
  const plan = doc.plan;
  if (!plan) return lines.join("\n").trim();
  if (plan.cells) {
    let days = "";
    for (const c of plan.cells) {
      if (c.days !== days) {
        days = c.days;
        lines.push(days);
      }
      if (c.status !== "ok") {
        lines.push(`  ${c.part} (${c.hours}): ${c.status === "closed" ? "closed" : "not enough scans yet"}`);
        continue;
      }
      lines.push(`  ${c.part} (${c.hours}), ${c.busy_label ?? "steady"}: ${c.acts.map((a) => a.name).join(", ")}`);
    }
  } else {
    lines.push(...(plan.acts ?? []).map((a) => `  ${a.name}`));
  }
  lines.push("", "Acts are modelled from Qloo's artist graph and your groups. Your own licensed music service supplies the tracks.");
  return lines.join("\n");
}
