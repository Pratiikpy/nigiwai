"use client";

import "maplibre-gl/dist/maplibre-gl.css";
import type { Map as MlMap, Marker } from "maplibre-gl";
import { useEffect, useRef } from "react";
import { GROUP_VARS, type AroundData, type CrowdMapData, type LayerId, type Mix, type Selection } from "@/lib/map";

// OpenFreeMap: free vector tiles from OpenStreetMap data, no account or key (https://openfreemap.org). The owner's
// browser fetches the tiles directly, so its address and the area it looks at reach OpenFreeMap; nothing about guests does.
const STYLE = { light: "https://tiles.openfreemap.org/styles/positron", dark: "https://tiles.openfreemap.org/styles/fiord" };

type Props = {
  data: CrowdMapData;
  around: AroundData | null;
  layers: Set<LayerId>;
  selection: Selection;
  theme: "light" | "dark";
  onSelect: (s: Selection) => void;
  onProblem: (message: string) => void;
};

const css = (name: string) => getComputedStyle(document.documentElement).getPropertyValue(name).trim() || "#888";

function pie(mix: Mix, size: number): string {
  // Conic slices as SVG arcs; a mix with nothing in it is a plain ring.
  const r = size / 2 - 3;
  const c = size / 2;
  let angle = -Math.PI / 2;
  const slices = mix
    .filter((m) => m.share > 0)
    .map((m) => {
      const next = angle + m.share * Math.PI * 2;
      const large = next - angle > Math.PI ? 1 : 0;
      const [x1, y1] = [c + r * Math.cos(angle), c + r * Math.sin(angle)];
      const [x2, y2] = [c + r * Math.cos(next), c + r * Math.sin(next)];
      const fill = m.group === null ? css("--ink-3") : css(GROUP_VARS[m.group % 3] ?? "--t1");
      const d = `M${c} ${c} L${x1} ${y1} A${r} ${r} 0 ${large} 1 ${x2} ${y2} Z`;
      angle = next;
      return `<path d="${d}" fill="${fill}"/>`;
    })
    .join("");
  return slices;
}

function circle(lat: number, lon: number, radius: number, steps = 64): [number, number][] {
  const out: [number, number][] = [];
  for (let i = 0; i <= steps; i++) {
    const a = (i / steps) * 2 * Math.PI;
    const dLat = (radius / 6371000) * Math.cos(a);
    const dLon = (radius / (6371000 * Math.cos((lat * Math.PI) / 180))) * Math.sin(a);
    out.push([lon + (dLon * 180) / Math.PI, lat + (dLat * 180) / Math.PI]);
  }
  return out;
}

/** The map canvas: base map, overlays for each layer, and one focusable button per site. Selection is owned by the page. */
export function CrowdMap({ data, around, layers, selection, theme, onSelect, onProblem }: Props) {
  const host = useRef<HTMLDivElement>(null);
  const map = useRef<MlMap | null>(null);
  const markers = useRef<Marker[]>([]);
  const draw = useRef<(() => void) | null>(null);
  const fitted = useRef(false);
  const styled = useRef(false); // true from the style's own load event until the style is replaced
  const everStyled = useRef(false);
  const lib = useRef<typeof import("maplibre-gl") | null>(null);
  const latest = useRef({ data, around, layers, selection, onSelect, onProblem });

  useEffect(() => {
    latest.current = { data, around, layers, selection, onSelect, onProblem };
    draw.current?.();
  }, [data, around, layers, selection, onSelect, onProblem]);

  useEffect(() => {
    let cancelled = false;
    let reportedTiles = false;
    let fellBack = false;
    (async () => {
      const ml = await import("maplibre-gl");
      if (cancelled || !host.current) return;
      // The bundler emits the map's worker as its own file; MapLibre is told where it is (their documented setup for Next.js).
      ml.setWorkerUrl(new URL("maplibre-gl/dist/maplibre-gl-worker.mjs", import.meta.url).toString());
      lib.current = ml;
      const first = latest.current.data.locations[0];
      let m: MlMap;
      try {
        m = new ml.Map({
          container: host.current,
          style: STYLE[theme],
          center: first ? [first.lon, first.lat] : [0, 20],
          zoom: first ? 13 : 2,
          attributionControl: { compact: true },
          cooperativeGestures: false,
        });
      } catch {
        latest.current.onProblem("Your browser can’t draw the map. The list shows the same information.");
        return;
      }
      map.current = m;
      m.addControl(new ml.NavigationControl({ showCompass: false }), "top-right");
      m.on("error", (e) => {
        // The base map's style could not be fetched at all: draw the layers on a plain background instead of nothing.
        if (!everStyled.current && !styled.current && !fellBack) {
          fellBack = true;
          m.setStyle({ version: 8, sources: {}, layers: [{ id: "plain", type: "background", paint: { "background-color": css("--bg-sunken") } }] });
        }
        if (reportedTiles) return;
        const status = (e.error as { status?: number } | undefined)?.status;
        if (status !== undefined || /Failed to fetch|NetworkError/i.test(String(e.error?.message))) {
          reportedTiles = true;
          latest.current.onProblem("The base map couldn’t be loaded, so streets are missing. Your sites and layers still show.");
        }
      });
      const sources = ["catchment", "radius", "around", "gaps"];
      const layerIds = ["catchment-fill", "catchment-line", "radius-line", "around-dot", "around-label", "gaps-fill", "gaps-line"];

      draw.current = () => {
        if (!map.current || !styled.current || !lib.current) return;
        const { data: d, around: ar, layers: on, selection: sel, onSelect: pick } = latest.current;
        const places = ar?.places ?? [];
        const mm = map.current;
        for (const id of layerIds) if (mm.getLayer(id)) mm.removeLayer(id);
        for (const id of sources) if (mm.getSource(id)) mm.removeSource(id);

        const colourOf = (g: number | null) => (g === null ? css("--ink-3") : css(GROUP_VARS[g % 3] ?? "--t1"));
        mm.addSource("catchment", {
          type: "geojson",
          data: {
            type: "FeatureCollection",
            features: d.catchment.map((c) => ({
              type: "Feature",
              properties: {
                cell: c.cell,
                colour: on.has("groups") ? colourOf(c.main_group) : css("--ink-3"),
                selected: sel?.kind === "cell" && sel.id === c.cell ? 1 : 0,
              },
              geometry: { type: "Polygon", coordinates: [[...c.boundary.map(([la, lo]) => [lo, la]), [c.boundary[0]![1], c.boundary[0]![0]]]] },
            })),
          },
        });
        mm.addSource("radius", {
          type: "geojson",
          data: {
            type: "FeatureCollection",
            features: d.locations.map((l) => ({ type: "Feature", properties: {}, geometry: { type: "LineString", coordinates: circle(l.lat, l.lon, l.radius_m) } })),
          },
        });
        const gap = d.gaps;
        mm.addSource("gaps", {
          type: "geojson",
          data: {
            type: "FeatureCollection",
            features: gap
              ? [
                  {
                    type: "Feature",
                    properties: { selected: sel?.kind === "gap" ? 1 : 0 },
                    geometry: { type: "Polygon", coordinates: [circle(gap.lat, gap.lon, gap.radius_m)] },
                  },
                ]
              : [],
          },
        });
        mm.addSource("around", {
          type: "geojson",
          data: {
            type: "FeatureCollection",
            features: places.map((p) => ({
              type: "Feature",
              properties: { id: p.entity_id, name: p.name, selected: sel?.kind === "place" && sel.id === p.entity_id ? 1 : 0 },
              geometry: { type: "Point", coordinates: [p.lon, p.lat] },
            })),
          },
        });
        const ink = css("--ink");
        const surface = css("--surface");
        mm.addLayer({
          id: "radius-line",
          type: "line",
          source: "radius",
          paint: { "line-color": ink, "line-opacity": 0.55, "line-width": 2, "line-dasharray": [2, 3] },
          layout: { visibility: on.has("sites") ? "visible" : "none" },
        });
        // A candidate gap is drawn as a dashed, lightly filled area in the warning colour: never as a place, because nothing is there.
        mm.addLayer({
          id: "gaps-fill",
          type: "fill",
          source: "gaps",
          paint: { "fill-color": css("--warn"), "fill-opacity": ["case", ["==", ["get", "selected"], 1], 0.26, 0.14] },
          layout: { visibility: on.has("gaps") ? "visible" : "none" },
        });
        mm.addLayer({
          id: "gaps-line",
          type: "line",
          source: "gaps",
          paint: { "line-color": css("--warn"), "line-width": ["case", ["==", ["get", "selected"], 1], 4, 2.5], "line-dasharray": [1.5, 2] },
          layout: { visibility: on.has("gaps") ? "visible" : "none" },
        });
        mm.addLayer({
          id: "catchment-fill",
          type: "fill",
          source: "catchment",
          paint: { "fill-color": ["get", "colour"], "fill-opacity": on.has("groups") ? 0.5 : 0.25 },
          layout: { visibility: on.has("catchment") ? "visible" : "none" },
        });
        mm.addLayer({
          id: "catchment-line",
          type: "line",
          source: "catchment",
          paint: { "line-color": ink, "line-opacity": ["case", ["==", ["get", "selected"], 1], 1, 0.35], "line-width": ["case", ["==", ["get", "selected"], 1], 3.5, 1.2] },
          layout: { visibility: on.has("catchment") ? "visible" : "none" },
        });
        mm.addLayer({
          id: "around-dot",
          type: "circle",
          source: "around",
          paint: {
            "circle-radius": ["case", ["==", ["get", "selected"], 1], 9, 6.5],
            "circle-color": surface,
            "circle-stroke-color": ink,
            "circle-stroke-width": ["case", ["==", ["get", "selected"], 1], 4, 2.5],
          },
          layout: { visibility: on.has("around") ? "visible" : "none" },
        });
        if (mm.getStyle().glyphs) mm.addLayer({
          id: "around-label",
          type: "symbol",
          source: "around",
          minzoom: 13.5,
          layout: {
            visibility: on.has("around") ? "visible" : "none",
            "text-field": ["get", "name"],
            "text-font": ["Noto Sans Bold"],
            "text-size": 12,
            "text-offset": [0, 1.1],
            "text-anchor": "top",
            "text-max-width": 9,
          },
          paint: { "text-color": ink, "text-halo-color": surface, "text-halo-width": 1.6 },
        });

        for (const marker of markers.current) marker.remove();
        markers.current = [];
        if (on.has("sites")) {
          for (const l of d.locations) {
            const button = document.createElement("button");
            button.type = "button";
            button.className = `mappin${sel?.kind === "location" && sel.id === l.id ? " is-on" : ""}${l.hidden ? " is-hidden" : ""}`;
            button.setAttribute(
              "aria-label",
              l.hidden ? `${l.name}, under ${d.min_group} guests` : `${l.name}, ${l.scans} scans`,
            );
            const size = l.hidden ? 46 : Math.min(76, 44 + Math.log2(Math.max(l.scans ?? 1, 1)) * 4);
            button.style.width = button.style.height = `${size}px`;
            button.innerHTML = `<svg viewBox="0 0 ${size} ${size}" width="${size}" height="${size}" aria-hidden="true" focusable="false">
              <circle cx="${size / 2}" cy="${size / 2}" r="${size / 2 - 1.5}" fill="${surface}" stroke="${ink}" stroke-width="3" ${l.hidden ? 'stroke-dasharray="4 4"' : ""}/>
              ${on.has("groups") && !l.hidden ? pie(l.mix, size) : ""}
              <circle cx="${size / 2}" cy="${size / 2}" r="${l.hidden ? size / 2 - 6 : size / 2 - 11}" fill="${css("--surface-inv")}"/>
              <text x="${size / 2}" y="${size / 2 + 4.5}" text-anchor="middle" font-size="${l.hidden ? 11 : 13}" font-weight="700" fill="${css("--ink-inv")}">${l.hidden ? "&lt;10" : l.scans}</text>
            </svg>`;
            button.addEventListener("click", (ev) => {
              ev.stopPropagation();
              pick({ kind: "location", id: l.id });
            });
            markers.current.push(new lib.current.Marker({ element: button }).setLngLat([l.lon, l.lat]).addTo(mm));
          }
        }

        // What is drawn, readable by the page's tests and by assistive tools that inspect the container.
        const box = host.current;
        if (box) {
          box.dataset.pins = String(on.has("sites") ? d.locations.length : 0);
          box.dataset.hexes = String(on.has("catchment") ? d.catchment.length : 0);
          box.dataset.places = String(on.has("around") ? places.length : 0);
          box.dataset.gaps = String(on.has("gaps") && d.gaps ? d.gaps.groups.length : 0);
        }

        if (!fitted.current && (d.locations.length || places.length)) {
          const b = new lib.current.LngLatBounds();
          for (const l of d.locations) b.extend([l.lon, l.lat]);
          for (const c of d.catchment) for (const [la, lo] of c.boundary) b.extend([lo, la]);
          if (d.gaps) for (const [lo, la] of circle(d.gaps.lat, d.gaps.lon, d.gaps.radius_m, 16)) b.extend([lo, la]);
          for (const p of places) b.extend([p.lon, p.lat]);
          if (!b.isEmpty()) {
            mm.fitBounds(b, { padding: 60, maxZoom: 14.5, duration: 0 });
            fitted.current = true;
          }
        }
      };

      m.on("style.load", () => {
        styled.current = true;
        everStyled.current = true;
        draw.current?.();
      });
      m.on("click", "catchment-fill", (e) => {
        const cell = e.features?.[0]?.properties?.cell as string | undefined;
        if (cell) latest.current.onSelect({ kind: "cell", id: cell });
      });
      m.on("click", "gaps-fill", () => latest.current.onSelect({ kind: "gap", id: "area" }));
      m.on("click", "around-dot", (e) => {
        const id = e.features?.[0]?.properties?.id as string | undefined;
        if (id) latest.current.onSelect({ kind: "place", id });
      });
      for (const layer of ["catchment-fill", "around-dot", "gaps-fill"]) {
        m.on("mouseenter", layer, () => (m.getCanvas().style.cursor = "pointer"));
        m.on("mouseleave", layer, () => (m.getCanvas().style.cursor = ""));
      }
      m.on("click", (e) => {
        const hit = m.queryRenderedFeatures(e.point, { layers: ["catchment-fill", "around-dot", "gaps-fill"].filter((id) => m.getLayer(id)) });
        if (!hit.length) latest.current.onSelect(null);
      });
      m.getContainer().setAttribute("data-ready", "1");
    })();
    return () => {
      cancelled = true;
      for (const marker of markers.current) marker.remove();
      markers.current = [];
      map.current?.remove();
      map.current = null;
      draw.current = null;
    };
    // The map is created once; theme changes go through the next effect and data through `latest`.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (!map.current) return;
    styled.current = false;
    map.current.setStyle(STYLE[theme]);
  }, [theme]);

  return <div ref={host} className="crowdmap" role="group" aria-label="Map of your sites. Use Tab to move between sites and Enter to inspect one." />;
}
