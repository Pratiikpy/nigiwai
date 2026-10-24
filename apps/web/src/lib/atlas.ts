/** Types and an example for the City Taste Atlas (PRD M16), as the API returns it. */

export type AtlasItem = {
  entity_id: string;
  name: string;
  responses: number;
  share: number;
  venues: number;
  /** The venue's own guests who picked it; null when fewer than 10, which is never shown as a number. */
  own: number | null;
};

export type AtlasGroup = { type: string; label: string; items: AtlasItem[] };

export type AtlasDoc = {
  state: "no_location" | "not_joined" | "waiting" | "ready";
  reason: string;
  opted_in: boolean;
  opted_in_at: string | null;
  has_location: boolean;
  limits: { venues_in_cell: number; responses_per_venue: number; responses_per_item: number; venues_per_item: number; max_share_of_one_venue: number };
  groups: AtlasGroup[];
  cell_responses: number | null;
  built_at: string | null;
};

/** An invented neighbourhood, shown only when the owner asks for it and always under a banner that says so. */
export const EXAMPLE: AtlasDoc = {
  state: "ready",
  reason: "",
  opted_in: true,
  opted_in_at: null,
  has_location: true,
  limits: { venues_in_cell: 5, responses_per_venue: 10, responses_per_item: 10, venues_per_item: 3, max_share_of_one_venue: 0.5 },
  cell_responses: 480,
  built_at: null,
  groups: [
    {
      type: "urn:entity:artist",
      label: "Artists",
      items: [
        { entity_id: "example-1", name: "Example act A", responses: 132, share: 0.275, venues: 6, own: 18 },
        { entity_id: "example-2", name: "Example act B", responses: 97, share: 0.202, venues: 5, own: null },
        { entity_id: "example-3", name: "Example act C", responses: 64, share: 0.133, venues: 4, own: 11 },
      ],
    },
    {
      type: "urn:entity:brand",
      label: "Brands",
      items: [
        { entity_id: "example-4", name: "Example brand D", responses: 88, share: 0.183, venues: 6, own: null },
        { entity_id: "example-5", name: "Example brand E", responses: 41, share: 0.085, venues: 3, own: null },
      ],
    },
  ],
};

export function percent(x: number): string {
  return `${Math.round(x * 100)}%`;
}
