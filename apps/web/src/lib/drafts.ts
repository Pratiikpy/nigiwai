/** Types for drafts (PRD M17, M10), as the API returns them. */

export type DraftKind = "outreach" | "event_page" | "social_post" | "ad_copy";

export const DRAFT_LABELS: Record<DraftKind, string> = {
  outreach: "Message to the act",
  event_page: "Event page",
  social_post: "Post",
  ad_copy: "Ad angle",
};

export type Draft = {
  id: string;
  kind: DraftKind;
  subject: string;
  body: string;
  status: "draft" | "approved" | "withdrawn";
  facts: Record<string, unknown>;
  source_key: string | null;
  created_at: string;
  edited_at: string | null;
  decided_at: string | null;
  gaps: string[];
  can_approve: boolean;
  why_not: string | null;
  mailto: string | null;
};

export type DraftSources = {
  actions: { key: string; title: string; act: string }[];
  groups: { index: number; label: string; loves: string[] }[];
};

export type DraftsDoc = { drafts: Draft[]; sources: DraftSources };

/** Square-bracket gaps in a text, as the server counts them: on one line, 1 to 80 characters. */
export function gapsIn(text: string): string[] {
  return [...new Set(text.match(/\[[^[\]\n]{1,80}\]/g) ?? [])];
}
