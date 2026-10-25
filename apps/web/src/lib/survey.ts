import type { IconName } from "@/components/Icon";
import type { PickerItem, PickerType } from "./api";

/** How each pickable type is presented: the label on its chip, the icon, and the colour group in the design system. */
export const CATEGORIES: Record<PickerType, { label: string; kind: string; icon: IconName; cat: string }> = {
  artist: { label: "Music", kind: "Artist", icon: "music", cat: "music" },
  tv_show: { label: "Shows", kind: "TV show", icon: "screen", cat: "shows" },
  movie: { label: "Films", kind: "Film", icon: "film", cat: "films" },
  brand: { label: "Brands", kind: "Brand", icon: "tag", cat: "brands" },
  book: { label: "Books", kind: "Book", icon: "book", cat: "books" },
  podcast: { label: "Podcasts", kind: "Podcast", icon: "mic", cat: "podcasts" },
  videogame: { label: "Games", kind: "Game", icon: "gamepad", cat: "games" },
  place: { label: "Places", kind: "Place", icon: "pin", cat: "places" },
};

/** What the search box invites, by the category chosen. A place is looked for near the venue the guest is in, on its own. */
export const SEARCH_PLACEHOLDER = "Band, show, film, book or brand";
export const PLACE_PLACEHOLDER = "A cafe, bar or restaurant near here";

/** Up to two capital letters for a tile: "The Lantern Hollow" -> "LH". */
export function initials(name: string): string {
  const words = name
    .replace(/^the\s+/i, "")
    .replace(/[^\p{L}\p{N} ]/gu, " ")
    .split(/\s+/)
    .filter(Boolean);
  const first = Array.from(words[0] ?? "?")[0] ?? "?";
  const second = Array.from(words[1] ?? "")[0] ?? "";
  return (first + second).toUpperCase();
}

export function metaLine(item: PickerItem): string {
  return [CATEGORIES[item.type]?.kind, item.year, item.disambiguation].filter(Boolean).join(" · ");
}

/** The sentence under the picker, and whether the guest can continue. */
export function pickProgress(count: number, min: number, max: number): { text: string; canContinue: boolean } {
  if (count < min) {
    const more = min - count;
    return {
      text: count === 0 ? `Pick at least ${min} to continue.` : `Pick ${more} more to continue.`,
      canContinue: false,
    };
  }
  if (count >= max) return { text: `All ${max} in. Nice.`, canContinue: true };
  return { text: `You can continue. Up to ${max - count} more if you like.`, canContinue: true };
}

export function countLine(count: number, max: number): string {
  return `${Math.min(count, max)} of ${max} picked`;
}

export type Segment = { text: string; strong: boolean };
export type Paragraph = Segment[];

/** The consent text is plain paragraphs with **bold** lead-ins. Parsed into data so it is rendered as text, never as HTML. */
export function parseConsent(body: string): Paragraph[] {
  return body
    .split(/\n\s*\n/)
    .map((block) => block.replace(/\s*\n\s*/g, " ").trim())
    .filter(Boolean)
    .map((block) => {
      const segments: Segment[] = [];
      const pattern = /\*\*(.+?)\*\*/g;
      let last = 0;
      for (const match of block.matchAll(pattern)) {
        const at = match.index ?? 0;
        if (at > last) segments.push({ text: block.slice(last, at), strong: false });
        segments.push({ text: match[1] ?? "", strong: true });
        last = at + match[0].length;
      }
      if (last < block.length) segments.push({ text: block.slice(last), strong: false });
      return segments;
    });
}

export const AGE_BANDS = ["18-24", "25-34", "35-44", "45-54", "55-64", "65+"] as const;
export const BUDGETS: { value: 1 | 2 | 3 | 4; label: string }[] = [
  { value: 1, label: "$ Easy on the wallet" },
  { value: 2, label: "$$ Somewhere in the middle" },
  { value: 3, label: "$$$ Treat myself" },
  { value: 4, label: "$$$$ Special occasions" },
];

export const ageLabel = (band: string) => band.replace("-", "–");

/** A short place name is all the district field accepts; the server enforces the same rule. */
export function districtProblem(value: string): string | null {
  const v = value.trim();
  if (!v) return null;
  if (v.length > 60) return "Keep it to 60 characters.";
  if (/@|https?:|www\./i.test(v) || /\d{5,}/.test(v)) return "Just the name of your area, for example “Eastside”.";
  return null;
}

/** The owner's list of areas, typed as one line with commas: each a short name, none repeated, at most twelve. */
export function parseAreas(line: string): { areas: string[]; problem: string | null } {
  const areas: string[] = [];
  const seen = new Set<string>();
  for (const part of line.split(/[,\n;]/)) {
    const name = part.trim().replace(/\s+/g, " ");
    if (!name) continue;
    const problem = districtProblem(name);
    if (problem || name.length > 40) return { areas, problem: name.length > 40 ? `“${name.slice(0, 20)}…” is longer than 40 characters.` : problem };
    const key = name.normalize("NFKD").replace(/\p{M}/gu, "").toLowerCase();
    if (seen.has(key)) return { areas, problem: `“${name}” is listed twice.` };
    seen.add(key);
    areas.push(name);
  }
  if (areas.length > 12) return { areas, problem: "At most twelve areas." };
  return { areas, problem: null };
}

// ---- the draft kept in the browser so a reload does not lose the picks -------------------------------------------
export type Draft = {
  picks: PickerItem[];
  age: string | null;
  district: string;
  budget: number | null;
};

const key = (token: string) => `nigiwai-draft:${token}`;

export function saveDraft(token: string, draft: Draft): void {
  try {
    sessionStorage.setItem(key(token), JSON.stringify(draft));
  } catch {
    /* storage can be blocked (private windows); the survey still works without it */
  }
}

export function loadDraft(token: string): Draft | null {
  try {
    const raw = sessionStorage.getItem(key(token));
    if (!raw) return null;
    const draft = JSON.parse(raw) as Partial<Draft>;
    if (!Array.isArray(draft.picks)) return null;
    const picks = draft.picks.filter(
      (p): p is PickerItem =>
        !!p && typeof p.entity_id === "string" && typeof p.name === "string" && p.type in CATEGORIES,
    );
    return {
      picks,
      age: typeof draft.age === "string" ? draft.age : null,
      district: typeof draft.district === "string" ? draft.district : "",
      budget: typeof draft.budget === "number" ? draft.budget : null,
    };
  } catch {
    return null;
  }
}

export function clearDraft(token: string): void {
  try {
    sessionStorage.removeItem(key(token));
  } catch {
    /* nothing to clear */
  }
}
