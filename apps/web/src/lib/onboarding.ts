/** Types for the onboarding interview and the dashboard plan (PRD M1), as the API returns them. */

export type FieldKind = "choice" | "multi" | "text" | "hours" | "number" | "days" | "list" | "yesno" | "place";
export type Hours = { open: string; close: string };

export type Question = {
  field: string;
  kind: FieldKind;
  text: string;
  why: string;
  optional: boolean;
  choices: { value: string; label: string }[] | null;
  max?: number;
  days?: string[];
};

export type Message = { role: "assistant" | "owner"; text: string; field: string | null };
export type Understood = { field: string; label: string; text: string };

export type PlanModule = {
  id: string;
  label: string;
  href: string;
  on: boolean;
  locked: boolean;
  available: boolean;
  reason: string;
  changed: boolean;
};

export type Interview = {
  id: string;
  mode: "form" | "agent";
  status: "open" | "confirmed" | "abandoned";
  agent_available: boolean;
  messages: Message[];
  question: Question | null;
  asked: number;
  max_questions: number;
  known: Record<string, unknown>;
  understood: Understood[];
  fields: Record<string, Question>;
  ready: boolean;
  business_name: string | null;
  profile: Record<string, unknown> | null;
  plan: { version: number; modules: PlanModule[] } | null;
  notice: string | null;
};

export type Plan = {
  version: number;
  profile_version: number;
  confirmed_at: string;
  modules: PlanModule[];
  overrides: Record<string, boolean>;
  profile: Record<string, unknown>;
  summary: Understood[];
};

export type OnboardingState = { agent_available: boolean; session: Interview | null; plan: Plan | null };
export type Confirmed = { business_id: string; profile_version: number; plan_version: number; plan: Plan };
export type Place = { label: string; lat: number; lon: number };

export const DAY_NAMES = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"];
export const DAY_SHORT = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];

/** The path of a module's page, so the side menu can hide the ones the plan leaves off. */
export const MODULE_OF_PATH: Record<string, string> = {
  "/app/map": "map",
  "/app/soundcheck": "soundcheck",
  "/app/brief": "brief",
  "/app/sound": "sound",
  "/app/moves": "moves",
  "/app/drafts": "drafts",
};
