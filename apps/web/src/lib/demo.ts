/** Judge mode: the public demo venues. The routes mirror an owner's venue under /public/demo/{slug}. */

export type DemoSummary = {
  place?: string;
  area?: string | null;
  events?: number | null;
  first?: string | null;
  last?: string | null;
  acts_matched?: number | null;
  performers?: number | null;
  top?: string[];
  wildcard?: string | null;
};

export type DemoVenue = {
  slug: string;
  name: string;
  city: string;
  blurb: string;
  summary: DemoSummary;
  refreshed_at: string | null;
  /** True for a venue a visitor asked for: kept for a week, listed nowhere. */
  requested: boolean;
  expires_at: string | null;
};

/** A venue found on MusicBrainz by name. `slug` and `status` are set when a demo venue already exists for it. */
export type FoundPlace = {
  mbid: string;
  name: string;
  area: string | null;
  address: string | null;
  kind: string | null;
  mappable: boolean;
  slug: string | null;
  status: "building" | "ready" | "failed" | null;
};

/** Where a requested venue's build stands. `reason` and `retry_at` come with a failure. */
export type RequestStatus = {
  slug: string;
  name: string;
  mbid: string | null;
  status: "building" | "ready" | "failed";
  reason?: string;
  retry_at?: string | null;
};

export const placeLine = (p: Pick<FoundPlace, "area" | "address" | "kind">) => [p.area, p.address, p.kind].filter(Boolean).join(" · ");

/** A venue's address says whether a visitor asked for it: the prepared ones have plain names, requested ones start with req-. */
export const isRequested = (slug: string) => slug.startsWith("req-");

export const demoBase = (slug: string) => `/public/demo/${slug}`;

/** "2009 to 2026" from the first and last event dates, which MusicBrainz may give as a year, a month or a day. */
export function years(s: DemoSummary): string | null {
  const a = s.first?.slice(0, 4);
  const b = s.last?.slice(0, 4);
  if (!a || !b) return null;
  return a === b ? a : `${a} to ${b}`;
}

export function matched(s: DemoSummary): string | null {
  if (s.acts_matched == null || s.performers == null) return null;
  return `${s.acts_matched} of ${s.performers} matched`;
}

export function timeOn(iso: string | null | undefined): string | null {
  if (!iso) return null;
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return null;
  return d.toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit" });
}

export function refreshedOn(iso: string | null): string | null {
  if (!iso) return null;
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return null;
  return d.toLocaleDateString("en-GB", { day: "numeric", month: "long", year: "numeric" });
}
