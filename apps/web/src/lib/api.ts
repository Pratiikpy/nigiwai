/** Typed access to the Nigiwai API through the same-origin `/api/v1` proxy. Nothing here talks to Qloo. */

export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly detail: string,
    readonly fields: { field: string; message: string }[] = [],
  ) {
    super(detail);
  }
}

let csrfToken: string | null = null;
export const setCsrf = (token: string | null) => {
  csrfToken = token;
};

type Options = { method?: string; body?: unknown; signal?: AbortSignal };

function describe(status: number, payload: unknown): ApiError {
  const detail = (payload as { detail?: unknown } | null)?.detail;
  if (typeof detail === "string") return new ApiError(status, detail);
  if (Array.isArray(detail)) {
    const fields = detail
      .filter((d): d is { field: string; message: string } => typeof d?.field === "string" && typeof d?.message === "string")
      .map((d) => ({ field: d.field, message: d.message }));
    return new ApiError(status, fields[0] ? `${fields[0].field}: ${fields[0].message}` : "That wasn't accepted.", fields);
  }
  return new ApiError(status, status >= 500 ? "Something went wrong on our side." : "That wasn't accepted.");
}

export async function api<T>(path: string, { method = "GET", body, signal }: Options = {}): Promise<T> {
  const headers: Record<string, string> = {};
  if (body !== undefined) headers["content-type"] = "application/json";
  if (method !== "GET" && csrfToken) headers["x-csrf-token"] = csrfToken;
  let response: Response;
  try {
    response = await fetch(`/api/v1${path}`, {
      method,
      headers,
      body: body === undefined ? undefined : JSON.stringify(body),
      credentials: "same-origin",
      signal,
    });
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError") throw error;
    throw new ApiError(0, "We couldn't reach the server. Check your connection and try again.");
  }
  if (response.status === 204) return undefined as T;
  let payload: unknown = null;
  try {
    payload = await response.json();
  } catch {
    /* a non-JSON body: fall through to the status-based message */
  }
  if (!response.ok) throw describe(response.status, payload);
  return payload as T;
}

/** POST that answers with a file (the share image). Same origin, same error handling. */
export async function apiBlob(path: string, body: unknown): Promise<Blob> {
  let response: Response;
  try {
    response = await fetch(`/api/v1${path}`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(body),
      credentials: "same-origin",
    });
  } catch {
    throw new ApiError(0, "We couldn't reach the server. Check your connection and try again.");
  }
  if (!response.ok) {
    let payload: unknown = null;
    try {
      payload = await response.json();
    } catch {
      /* not JSON */
    }
    throw describe(response.status, payload);
  }
  return response.blob();
}

// ---- shapes (mirrors apps/api/src/nigiwai_api/schemas.py) -----------------------------------------------------
export type PickerType = "artist" | "movie" | "tv_show" | "book" | "brand" | "podcast" | "videogame";

export type Questions = {
  min_picks: number;
  max_picks: number;
  ask_age_band: boolean;
  ask_district: boolean;
  ask_budget: boolean;
  picker_types: PickerType[];
};
export type Reward = { title: string; detail: string };

export type PublicSurvey = {
  business_name: string;
  location_name: string;
  qr_label: string;
  questions: Questions;
  reward: Reward | null;
  consent_text_version: string;
  consent_body: string;
  nonce: string;
  picker_min_chars: number;
};

export type PickerItem = {
  entity_id: string;
  name: string;
  type: PickerType;
  year: number | null;
  description: string | null;
  disambiguation: string | null;
};
export type PickerResult = { items: PickerItem[]; source: "local" | "qloo" | "cache" | "none"; message: string | null };
export type SelectResult = { entity_id: string; eligible: boolean | null; message: string | null };
export type AgeBand = "18-24" | "25-34" | "35-44" | "45-54" | "55-64" | "65+";
export type ResponseResult = { ok: boolean; receipt: string; reward: Reward | null };

export type Tenant = { id: string; name: string; role: "owner" | "manager" | "viewer" };
export type Me = { user_id: string; email: string; csrf_token: string; tenants: Tenant[] };
export type Business = { id: string; tenant_id: string; name: string; type: string; language: string; currency: string };
export type Location = {
  id: string;
  business_id: string;
  name: string;
  address: string | null;
  lat: number | null;
  lon: number | null;
  radius_m: number;
  timezone: string;
  price_level: number | null;
  capacity: number | null;
  curfew: string | null;
  excluded_genres: string[];
  show_nights: number[];
};
export type QrPoint = {
  id: string;
  location_id: string;
  label: string;
  status: "active" | "revoked";
  token_hint: string;
  created_at: string;
  url: string | null;
};
export type Survey = {
  id: string;
  version: number;
  business_id: string;
  status: "draft" | "published" | "archived";
  questions: Questions;
  reward: Reward | null;
  consent_text_version: string;
};
export type Stats = {
  responses: number;
  held_for_review: number;
  qr_points: { id: string; label: string; responses: number }[];
};

export type CardGroup = {
  status: "matched" | "forming";
  label: string | null;
  provisional: boolean;
  line: string;
  share_text: string;
  share: number | null;
  n: number;
  needed?: number;
};
export type TasteCardData = {
  venue: string;
  group: CardGroup;
  picks: { entity_id: string; name: string; type: string }[];
  reward: Reward | null;
  can_fill_in: boolean;
};
export type CardEntity = {
  entity_id: string;
  name: string;
  type: string;
  year: number | null;
  description: string | null;
  distance_m?: number | null;
  address?: string | null;
};
export type CardExtras = {
  status: "ok" | "slow" | "unavailable";
  related: { because: string; items: CardEntity[] }[];
  near: CardEntity[];
  calls?: number | null;
};
