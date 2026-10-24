import type { LabelKind } from "@/components/Label";

export type Mode = "crowd" | "culture";

export type AskItem = {
  entity_id: string;
  rank: number;
  name: string;
  type: string;
  reason: string;
  provenance: "surfaced" | "confirmed" | "yours";
  label: LabelKind;
  call: string;
  detail: string | null;
};

export type Answer = {
  id: string;
  question: string;
  created_at: string;
  mode: Mode;
  kind: "model" | "template";
  verdict: string;
  items: AskItem[];
  rejected: { entity_id: string; reason: string }[];
  evidence: { label: LabelKind; text: string }[];
  what_would_change: string[];
  not_enough_data: { reason: string; unlock: string[] } | null;
  warnings: string[];
  notes: string[];
  stats: { qloo_calls: number; model_turns: number; tools: string[]; seconds: number };
};

export type TraceCall = {
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
};

export type Past = { id: string; mode: Mode; question: string; kind: "model" | "template"; verdict: string | null; created_at: string };

export type LiveStep = { text: string; tool: string };
export type LiveCall = { tool: string; status: string; cache: string; results: number; left: number };

export const SUGGESTIONS: Record<Mode, string[]> = {
  crowd: [
    "Who should I book next, and would they suit my crowd?",
    "What could fill my quietest hours?",
    "What do my groups love that I do not offer yet?",
  ],
  culture: [
    "What else do people who love jazz tend to enjoy?",
    "Which bars near me suit a quiet weeknight crowd?",
    "Which acts are close to the ones I already book?",
  ],
};

/** The label a provenance gets in plain words. */
export function provenanceText(p: AskItem["provenance"]): string {
  if (p === "yours") return "One of your own guests’ favourites, from your survey";
  return p === "surfaced" ? "Surfaced by Qloo" : "Proposed by the assistant, confirmed by Qloo";
}

/** The parameters of a call as a short line, with long id lists shortened to a count. */
export function paramsText(params: [string, string][]): string {
  return params
    .map(([k, v]) => {
      const n = v.split(",").length;
      return n > 2 && v.length > 60 ? `${k}=[${n} ids]` : `${k}=${v}`;
    })
    .join("  ");
}
