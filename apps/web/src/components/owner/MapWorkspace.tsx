"use client";

import dynamic from "next/dynamic";
import Link from "next/link";
import { useCallback, useEffect, useMemo, useState, useSyncExternalStore } from "react";
import { Icon } from "@/components/Icon";
import { Label } from "@/components/Label";
import { Loading, Notice, PageHead } from "@/components/owner/ui";
import { ApiError, api } from "@/lib/api";
import { GROUP_VARS, LAYERS, type AroundData, type AroundPlace, type Catchment, type CrowdMapData, type LayerId, type MapLocation, type Mix, type Selection } from "@/lib/map";

// The map needs the browser (WebGL), so it is loaded only here and only on the client.
const CrowdMap = dynamic(() => import("@/components/owner/CrowdMap").then((m) => m.CrowdMap), {
  ssr: false,
  loading: () => <Loading label="Loading the map…" />,
});

const PERIODS = [
  { id: "7d", label: "7 days" },
  { id: "4w", label: "4 weeks" },
  { id: "all", label: "All time" },
] as const;

function useTheme(): "light" | "dark" {
  return useSyncExternalStore(
    (notify) => {
      const observer = new MutationObserver(notify);
      observer.observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });
      return () => observer.disconnect();
    },
    () => (document.documentElement.getAttribute("data-theme") === "dark" ? "dark" : "light"),
    () => "light",
  );
}

const pct = (x: number) => `${Math.round(x * 100)}%`;
const sel = (s: Selection) => (s ? `${s.kind}:${s.id}` : "");
const parseSel = (v: string | null): Selection => {
  const m = /^(location|cell|place):(.+)$/.exec(v ?? "");
  return m ? ({ kind: m[1], id: m[2] } as Selection) : null;
};

function MixBars({ mix }: { mix: Mix }) {
  if (!mix.length) return <p className="meta">No grouping yet.</p>;
  return (
    <ul className="legend-list" role="list" aria-label="Group mix">
      {mix.map((m) => (
        <li key={m.label}>
          <i className="tribe__dot" style={{ background: m.group === null ? "var(--ink-3)" : `var(${GROUP_VARS[m.group % 3]})` }} aria-hidden="true" />
          <span>{m.label}</span>
          <span className="num">{pct(m.share)}</span>
        </li>
      ))}
    </ul>
  );
}

function Inspector({ data, around, selection, demo }: { data: CrowdMapData; around: AroundData | null; selection: Selection; demo: boolean }) {
  const [tab, setTab] = useState<"inspect" | "proof">("inspect");
  const location = selection?.kind === "location" ? data.locations.find((l) => l.id === selection.id) : undefined;
  const cell = selection?.kind === "cell" ? data.catchment.find((c) => c.cell === selection.id) : undefined;
  const placeHit = selection?.kind === "place" ? around?.places.find((p) => p.entity_id === selection.id) : undefined;
  return (
    <aside className="card mapx__side" aria-label="Inspector" data-testid="inspector">
      <div className="tabs" role="tablist" aria-label="Inspector">
        <button className="tab" role="tab" type="button" id="tab-inspect" aria-selected={tab === "inspect"} aria-controls="insp-body" onClick={() => setTab("inspect")}>
          Inspect
        </button>
        <button className="tab" role="tab" type="button" id="tab-proof" aria-selected={tab === "proof"} aria-controls="proof-body" onClick={() => setTab("proof")}>
          Proof
        </button>
      </div>
      {tab === "inspect" ? (
        <div className="stack" role="tabpanel" id="insp-body" aria-labelledby="tab-inspect" tabIndex={0}>
          {location ? <LocationView l={location} data={data} /> : null}
          {cell ? <CellView c={cell} /> : null}
          {placeHit ? <PlaceView p={placeHit} dropped={around?.dropped_closed ?? 0} /> : null}
          {!location && !cell && !placeHit ? <Overview data={data} demo={demo} /> : null}
        </div>
      ) : (
        <div className="stack" role="tabpanel" id="proof-body" aria-labelledby="tab-proof" tabIndex={0}>
          <p className="meta">What Qloo was asked to draw the “Around you” layer, and how it answered. Guests’ answers never go to Qloo.</p>
          {around && around.calls.length ? (
            <ul className="calls" role="list">
              {around.calls.map((c, i) => (
                <li key={c.id}>
                  {i + 1}. {c.endpoint} → {c.status}, {c.results} {c.results === 1 ? "result" : "results"}, {c.cache === "miss" ? `${c.latency_ms} ms` : "from cache"}
                  <details className="disc">
                    <summary>
                      <Icon name="chev-r" />
                      What was sent
                    </summary>
                    <div className="disc__body">
                      <code className="mono">{c.params.map(([k, v]) => `${k}=${v}`).join("&")}</code>
                    </div>
                  </details>
                </li>
              ))}
            </ul>
          ) : (
            <p className="meta">No Qloo call was needed for what is on the map.</p>
          )}
        </div>
      )}
    </aside>
  );
}

function Overview({ data, demo }: { data: CrowdMapData; demo: boolean }) {
  const scans = data.locations.reduce((a, l) => a + (l.scans ?? 0), 0);
  return (
    <>
      <div>
        <p className="eyebrow">{data.business}</p>
        <h2 className="insp__t">Select something on the map</h2>
      </div>
      <p>
        <Label kind="measured" detail={`${scans} scans`} /> {data.locations.length} {data.locations.length === 1 ? "site" : "sites"}. Pick a site, a hexagon or a place to see its
        sample size, where it comes from and how it was computed.
      </p>
      <p className="meta">
        Nothing is shown about fewer than {data.min_group} guests. A site or neighbourhood below that is a pin or counted, never described.
      </p>
      {data.grouping.state === "none" || data.grouping.state === "unstable" ? (
        <Notice tone="warn">
          Groups appear from 60 guests.{demo ? "" : " "}{demo ? null : <Link href="/app/people">See My people</Link>}{demo ? null : "."}
        </Notice>
      ) : null}
    </>
  );
}

function LocationView({ l, data }: { l: MapLocation; data: CrowdMapData }) {
  return (
    <>
      <div>
        <p className="eyebrow">Your site</p>
        <h2 className="insp__t">{l.name}</h2>
        {l.address ? <p className="meta">{l.address}</p> : null}
      </div>
      {l.hidden ? (
        <Notice tone="warn">
          <strong>Under {data.min_group} guests.</strong> Until {data.min_group} guests have scanned here, nothing about this site is shown beyond its pin.
        </Notice>
      ) : (
        <>
          <p>
            <Label kind="measured" detail={`n = ${l.scans}`} /> scans in this period.
          </p>
          <section className="stack stack--sm">
            <h3 className="insp__h">
              Who scans here <Label kind="modelled" detail="groups" />
            </h3>
            <MixBars mix={l.mix} />
            <p className="meta">Everyone is a mix of groups, so this is the average, not a headcount per box.</p>
          </section>
          {l.qr_points.length ? (
            <section className="stack stack--sm">
              <h3 className="insp__h">QR points</h3>
              <ul className="legend-list" role="list">
                {l.qr_points.map((q) => (
                  <li key={q.label}>
                    <span aria-hidden="true" />
                    <span>{q.label}</span>
                    <span className="num">{q.scans}</span>
                  </li>
                ))}
              </ul>
              <p className="meta">QR points with fewer than {data.min_group} scans are not listed.</p>
            </section>
          ) : null}
        </>
      )}
      <details className="disc">
        <summary>
          <Icon name="chev-r" />
          How this was computed
        </summary>
        <div className="disc__body">
          <p>
            Scans are counted from your guests’ answers at this site’s QR points. Each guest is placed among your groups from the tags Qloo attaches to what they picked;
            the mix adds those shares up. A group with fewer than {data.min_group} guests here is folded into “Other”.
          </p>
        </div>
      </details>
    </>
  );
}

function CellView({ c }: { c: Catchment }) {
  return (
    <>
      <div>
        <p className="eyebrow">Catchment</p>
        <h2 className="insp__t">{c.districts.join(", ")}</h2>
      </div>
      <p>
        <Label kind="measured" detail={`n = ${c.guests}`} /> guests named {c.districts.length === 1 ? "this neighbourhood" : "these neighbourhoods"} as where they come from.
      </p>
      <section className="stack stack--sm">
        <h3 className="insp__h">
          Who they are <Label kind="modelled" detail="groups" />
        </h3>
        <MixBars mix={c.mix} />
      </section>
      <details className="disc">
        <summary>
          <Icon name="chev-r" />
          How this was computed
        </summary>
        <div className="disc__body">
          <p>
            Guests may type where they come from (optional, a short place name). Names are counted without regard to case or spacing; one that at least ten guests gave is looked up on
            OpenStreetMap near your venue and drawn as the hexagon it falls in. Smaller ones are only counted.
          </p>
        </div>
      </details>
    </>
  );
}

function PlaceView({ p, dropped }: { p: AroundPlace; dropped: number }) {
  return (
    <>
      <div>
        <p className="eyebrow">Around you</p>
        <h2 className="insp__t">{p.name}</h2>
        {p.address ? <p className="meta">{p.address}</p> : null}
      </div>
      <p>
        <Label kind="observed" detail="from Qloo" />
        {p.distance_m !== null ? ` ${p.distance_m} m from your venue.` : ""}
      </p>
      <p className="meta">
        Qloo says this place is here and open. Place data can be stale: check before you plan around it.
        {dropped ? ` ${dropped} ${dropped === 1 ? "place" : "places"} Qloo marks as closed ${dropped === 1 ? "was" : "were"} left off.` : ""}
      </p>
    </>
  );
}

function Timeline({ data, period, onPeriod }: { data: CrowdMapData; period: CrowdMapData["period"]; onPeriod: (p: CrowdMapData["period"]) => void }) {
  const max = Math.max(1, ...data.timeline.buckets.map((b) => b.scans));
  return (
    <div className="timeline" data-testid="timeline">
      <div className="timeline__top">
        <div className="seg" role="group" aria-label="Period">
          {PERIODS.map((p) => (
            <button key={p.id} type="button" aria-pressed={period === p.id} onClick={() => onPeriod(p.id)}>
              {p.label}
            </button>
          ))}
        </div>
        <p className="meta">
          {data.timeline.total} {data.timeline.total === 1 ? "scan" : "scans"} in {period === "all" ? "all time" : period === "4w" ? "the last 4 weeks" : "the last 7 days"} <Label kind="measured" />
        </p>
      </div>
      {data.timeline.buckets.length ? (
        <div
          className="mapx__bars"
          role="img"
          aria-label={`Scans per ${data.timeline.unit}: ${data.timeline.buckets.map((b) => `${b.start} ${b.scans}`).join(", ")}`}
        >
          {data.timeline.buckets.map((b) => (
            <span key={b.start} title={`${b.start}: ${b.scans}`} style={{ ["--h" as string]: `${Math.max(6, (b.scans / max) * 100)}%` }} />
          ))}
        </div>
      ) : (
        <p className="meta">No scans in this period.</p>
      )}
    </div>
  );
}

function ListView({ data, around, onSelect }: { data: CrowdMapData; around: AroundData | null; onSelect: (s: Selection) => void }) {
  return (
    <div className="card stack" data-testid="list-view">
      <h2 className="card__title">Everything on the map</h2>
      <table className="listtable">
        <caption className="sr-only">Sites, neighbourhoods and places</caption>
        <thead>
          <tr>
            <th scope="col">Kind</th>
            <th scope="col">Name</th>
            <th scope="col">Figure</th>
          </tr>
        </thead>
        <tbody>
          {data.locations.map((l) => (
            <tr key={l.id}>
              <td>Your site</td>
              <th scope="row">
                <button className="btn btn--sm btn--ghost" type="button" onClick={() => onSelect({ kind: "location", id: l.id })}>
                  {l.name}
                </button>
              </th>
              <td>{l.hidden ? `under ${data.min_group}` : `${l.scans} scans`}</td>
            </tr>
          ))}
          {data.catchment.map((c) => (
            <tr key={c.cell}>
              <td>Catchment</td>
              <th scope="row">
                <button className="btn btn--sm btn--ghost" type="button" onClick={() => onSelect({ kind: "cell", id: c.cell })}>
                  {c.districts.join(", ")}
                </button>
              </th>
              <td>{c.guests} guests</td>
            </tr>
          ))}
          {(around?.places ?? []).map((p) => (
            <tr key={p.entity_id}>
              <td>Around you</td>
              <th scope="row">
                <button className="btn btn--sm btn--ghost" type="button" onClick={() => onSelect({ kind: "place", id: p.entity_id })}>
                  {p.name}
                </button>
              </th>
              <td>{p.distance_m === null ? "" : `${p.distance_m} m`}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/** The crowd map for one venue; `base` is the API path of the venue (an owner's own, or a public demo venue's). */
export function MapWorkspace({ base, demo = false }: { base: string; demo?: boolean }) {
  const theme = useTheme();
  const initial = typeof window === "undefined" ? new URLSearchParams() : new URLSearchParams(window.location.search);
  const [period, setPeriod] = useState<CrowdMapData["period"]>((["7d", "4w"].includes(initial.get("period") ?? "") ? initial.get("period") : "all") as CrowdMapData["period"]);
  const [layers, setLayers] = useState<Set<LayerId>>(
    () => new Set((initial.get("layers") ?? "sites,groups,catchment,around").split(",").filter((l): l is LayerId => LAYERS.some((x) => x.id === l))),
  );
  const [selection, setSelection] = useState<Selection>(() => parseSel(initial.get("sel")));
  const [view, setView] = useState<"map" | "list">(initial.get("view") === "list" ? "list" : "map");
  const [data, setData] = useState<CrowdMapData | null>(null);
  const [around, setAround] = useState<AroundData | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  const [mapProblem, setMapProblem] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);
  const [tick, setTick] = useState(0);

  useEffect(() => {
    let live = true;
    api<CrowdMapData>(`${base}/map?period=${period}`)
      .then((d) => {
        if (!live) return;
        setData(d);
        setProblem(null);
      })
      .catch((e: unknown) => live && setProblem(e instanceof ApiError ? e.detail : "We couldn’t load the map."));
    return () => {
      live = false;
    };
  }, [base, period, tick]);

  // What is around the venue waits on Qloo, so it comes separately: the map is on screen without it.
  useEffect(() => {
    let live = true;
    api<AroundData>(`${base}/map/around`)
      .then((d) => live && setAround(d))
      .catch(() => live && setAround({ status: "unavailable", places: [], dropped_closed: 0, calls: [] }));
    return () => {
      live = false;
    };
  }, [base]);

  // Neighbourhoods are placed a few at a time: while some are still being located, ask again.
  const locating = data?.catchment_pending ?? 0;
  useEffect(() => {
    if (!locating) return;
    const timer = setTimeout(() => setTick((t) => t + 1), 3500);
    return () => clearTimeout(timer);
  }, [locating, data]);

  // The view is saved in the address, so a link reopens it as it was.
  useEffect(() => {
    // Only this view's own keys are rewritten; anything else in the address (the demo page's tab) is left alone.
    const q = new URLSearchParams(window.location.search);
    for (const key of ["period", "layers", "sel", "view"]) q.delete(key);
    if (period !== "all") q.set("period", period);
    q.set("layers", [...layers].join(","));
    if (selection) q.set("sel", sel(selection));
    if (view === "list") q.set("view", "list");
    window.history.replaceState(null, "", `?${q.toString()}`);
  }, [period, layers, selection, view]);

  const toggle = (id: LayerId) =>
    setLayers((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  const onSelect = useCallback((s: Selection) => setSelection(s), []);
  const onProblem = useCallback((m: string) => {
    setMapProblem(m);
    if (m.includes("can’t draw")) setView("list");
  }, []);
  const share = useMemo(
    () => async () => {
      await navigator.clipboard?.writeText(window.location.href);
      setCopied(true);
    },
    [],
  );

  if (!data) return problem ? <Notice tone="error">{problem}</Notice> : <Loading />;

  const noPoints = data.locations.length === 0;
  return (
    <>
      <PageHead
        title="Crowd map"
        as={demo ? "h2" : "h1"}
        lead={
          demo
            ? "Where this room sits and what Qloo says is around it. Every layer says how it was worked out."
            : "Where your guests scan, who they are, where they say they come from, and what is around. Every layer says how it was worked out."
        }
      >
        <div className="row row--wrap">
          <div className="seg" role="group" aria-label="View">
            <button type="button" aria-pressed={view === "map"} onClick={() => setView("map")}>
              Map
            </button>
            <button type="button" aria-pressed={view === "list"} onClick={() => setView("list")}>
              List
            </button>
          </div>
          <button className="btn btn--sm" type="button" onClick={() => void share()}>
            <Icon name="copy" size="sm" />
            {copied ? "Link copied" : "Copy view link"}
          </button>
        </div>
      </PageHead>

      {problem ? <Notice tone="error">{problem}</Notice> : null}
      {noPoints ? <Notice tone="warn">Your venue has no location yet. Add its address and position on Your venue to see it here.</Notice> : null}
      {mapProblem ? <Notice tone="warn">{mapProblem}</Notice> : null}
      {data.grouping.state !== "provisional" && data.grouping.state !== "named" ? (
        <Notice tone="warn">
          <strong>Groups come from 60 guests.</strong> Until then the map shows scans and what is around; sites show no mix.{demo ? " This venue is shown from public lineups, so there are no guest scans yet." : " "}{demo ? null : <Link href="/app/people">See My people</Link>}{demo ? null : "."}
        </Notice>
      ) : null}
      {data.catchment_pending ? (
        <p className="meta" role="status">
          Placing {data.catchment_pending} {data.catchment_pending === 1 ? "neighbourhood" : "neighbourhoods"} on the map…
        </p>
      ) : null}

      <div className="layerbar" role="group" aria-label="Map layers">
        {LAYERS.map((l) => (
          <button key={l.id} type="button" className="chipbtn layerchip" aria-pressed={layers.has(l.id)} onClick={() => toggle(l.id)}>
            <Icon name={l.icon} size="sm" />
            {l.label}
          </button>
        ))}
      </div>

      <div className="mapx">
        <div className="mapx__col">
          {view === "map" && !noPoints ? (
            <div className="mapx__frame">
              <CrowdMap data={data} around={around} layers={layers} selection={selection} theme={theme} onSelect={onSelect} onProblem={onProblem} />
              {around?.status === "unavailable" && layers.has("around") ? (
                <p className="mapx__note">Qloo couldn’t be reached, so “Around you” is empty for now.</p>
              ) : null}
            </div>
          ) : (
            <ListView data={data} around={around} onSelect={onSelect} />
          )}
          <p className="meta">
            {data.catchment_hidden.districts
              ? `${data.catchment_hidden.districts} ${data.catchment_hidden.districts === 1 ? "neighbourhood" : "neighbourhoods"} named by fewer than ${data.min_group} guests ${data.catchment_hidden.districts === 1 ? "is" : "are"} counted, not shown. `
              : ""}
            Sites and neighbourhoods below {data.min_group} guests are never described. Base map: OpenFreeMap, © OpenStreetMap contributors.
          </p>
          <Timeline data={data} period={period} onPeriod={setPeriod} />
        </div>
        <Inspector data={data} around={around} selection={selection} demo={demo} />
      </div>
    </>
  );
}
