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
};

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

export function refreshedOn(iso: string | null): string | null {
  if (!iso) return null;
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return null;
  return d.toLocaleDateString("en-GB", { day: "numeric", month: "long", year: "numeric" });
}
