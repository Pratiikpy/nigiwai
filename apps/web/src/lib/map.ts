// What GET /businesses/{id}/map returns (apps/api/src/nigiwai_api/services/mapdata.py). Anything about fewer than ten
// guests has already been removed by the server.

export type Mix = { group: number | null; label: string; share: number }[];

export type MapLocation = {
  id: string;
  name: string;
  address: string | null;
  lat: number;
  lon: number;
  radius_m: number;
  scans: number | null;
  hidden: boolean;
  mix: Mix;
  qr_points: { label: string; scans: number }[];
};

export type Catchment = {
  cell: string;
  boundary: [number, number][];
  guests: number;
  districts: string[];
  main_group: number | null;
  main_label: string | null;
  mix: Mix;
};

export type AroundPlace = {
  entity_id: string;
  name: string;
  lat: number;
  lon: number;
  distance_m: number | null;
  address: string | null;
};

export type AroundData = {
  status: "ok" | "empty" | "unavailable";
  places: AroundPlace[];
  dropped_closed: number;
  calls: {
    id: string;
    at: string;
    purpose: string;
    endpoint: string;
    params: [string, string][];
    status: string;
    transport: string;
    cache: string;
    latency_ms: number;
    results: number;
  }[];
};

export type CrowdMapData = {
  business: string;
  period: "7d" | "4w" | "all";
  computed_at: string;
  locations: MapLocation[];
  groups: { index: number; label: string; share: number | null }[];
  grouping: { state: "none" | "unstable" | "provisional" | "named"; n: number; shown: number };
  catchment: Catchment[];
  catchment_hidden: { districts: number; guests: number };
  catchment_pending: number;
  timeline: { unit: "day" | "week"; buckets: { start: string; scans: number }[]; total: number };
  min_group: number;
};

export type Selection =
  | { kind: "location"; id: string }
  | { kind: "cell"; id: string }
  | { kind: "place"; id: string }
  | null;

export type LayerId = "sites" | "groups" | "catchment" | "around";
export const LAYERS: { id: LayerId; label: string; icon: "pin" | "people" | "hex" | "search" }[] = [
  { id: "sites", label: "Your sites", icon: "pin" },
  { id: "groups", label: "Groups", icon: "people" },
  { id: "catchment", label: "Catchment", icon: "hex" },
  { id: "around", label: "Around you", icon: "search" },
];

export const GROUP_VARS = ["--t1", "--t2", "--t3"];
