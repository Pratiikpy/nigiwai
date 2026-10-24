"use client";

import { useCallback, useEffect, useState } from "react";
import { Icon } from "@/components/Icon";
import { Label } from "@/components/Label";
import { ApiError, api } from "@/lib/api";
import { Notice } from "./ui";

type PlaceHit = { mbid: string; name: string; area: string | null; address: string | null; kind: string | null };
type Lineup = {
  place: { mbid: string; name: string; area: string | null };
  status: "queued" | "running" | "ready" | "failed";
  progress: { events?: number; performers?: number; stage?: string };
  error: string | null;
  result: {
    label: string;
    state: "profile" | "insufficient";
    reason: string;
    events: { used: number; with_lineup: number; first: string | null; last: string | null };
    performers: { unique: number; resolved: number; rate: number };
    top_acts: { name: string; mbid: string; entity_id: string | null; events: number }[];
    top_tags: { tag_id: string; name: string; acts: number; share: number }[];
    top_feel: { tag_id: string; name: string; acts: number; share: number }[];
    qloo_calls?: number;
    groups: { state: string; tribes: { label: string; shown: boolean; top_tags: { name: string }[]; top_items: { name: string }[]; share: number }[] } | null;
  } | null;
} | null;

const year = (d: string | null) => (d ? d.slice(0, 4) : "");

/**
 * For a venue with no guests yet: pick the venue in MusicBrainz and read who has played there. Everything it shows
 * is labelled as modelled from public lineups, with how many events and how many acts Qloo could match exactly.
 */
export function LineupStart({ tenantPath, businessId, canWrite }: { tenantPath: string; businessId: string; canWrite: boolean }) {
  const base = `${tenantPath}/businesses/${businessId}/lineup`;
  const [lineup, setLineup] = useState<Lineup | undefined>(undefined);
  const [query, setQuery] = useState("");
  const [hits, setHits] = useState<PlaceHit[] | null>(null);
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  const [tick, setTick] = useState(0);
  const reload = useCallback(() => setTick((t) => t + 1), []);

  useEffect(() => {
    let live = true;
    api<Lineup>(base)
      .then((l) => live && setLineup(l))
      .catch((e: unknown) => live && setProblem(e instanceof ApiError ? e.detail : "We couldn't load this."));
    return () => {
      live = false;
    };
  }, [base, tick]);

  const working = lineup?.status === "queued" || lineup?.status === "running";
  useEffect(() => {
    if (!working) return;
    const timer = setInterval(reload, 3000);
    return () => clearInterval(timer);
  }, [working, reload]);

  const search = async (event: React.FormEvent) => {
    event.preventDefault();
    if (busy || query.trim().length < 2) return;
    setBusy(true);
    setProblem(null);
    try {
      setHits(await api<PlaceHit[]>(`${base}/search?q=${encodeURIComponent(query.trim())}`));
    } catch (e) {
      setProblem(e instanceof ApiError ? e.detail : "The search didn't work. Please try again.");
    } finally {
      setBusy(false);
    }
  };

  const choose = async (hit: PlaceHit) => {
    setBusy(true);
    setProblem(null);
    try {
      await api(base, { method: "POST", body: { mbid: hit.mbid, name: hit.name, area: hit.area } });
      setHits(null);
      reload();
    } catch (e) {
      setProblem(e instanceof ApiError ? e.detail : "We couldn't start that.");
    } finally {
      setBusy(false);
    }
  };

  const remove = async () => {
    setBusy(true);
    try {
      await api(base, { method: "DELETE" });
      setLineup(null);
    } catch (e) {
      setProblem(e instanceof ApiError ? e.detail : "We couldn't remove that.");
    } finally {
      setBusy(false);
    }
  };

  if (lineup === undefined && !problem) return null;
  const r = lineup?.result;

  return (
    <section className="card stack" aria-labelledby="h-lineup">
      <div className="row row--between row--wrap">
        <h2 className="card__title" id="h-lineup">
          Start from public lineups
        </h2>
        {r ? <Label kind="modelled" detail="from public lineups" /> : null}
      </div>
      <p className="muted">
        No guests yet? See who has played at your venue (or one like it) from public event listings, matched to Qloo.
        It is a picture of the room, not of your guests, and it goes away once your own guests answer.
      </p>

      {problem ? <Notice tone="error">{problem}</Notice> : null}

      {!lineup && canWrite ? (
        <form className="stack stack--sm" onSubmit={search}>
          <div className="field">
            <label htmlFor="lineup-q">Venue name</label>
            <div className="row row--wrap">
              <input
                id="lineup-q"
                className="input grow"
                value={query}
                maxLength={100}
                onChange={(e) => setQuery(e.target.value)}
                placeholder="Mercury Lounge"
              />
              <button className="btn" type="submit" disabled={busy || query.trim().length < 2}>
                <Icon name="search" size="sm" />
                {busy ? "Searching…" : "Search"}
              </button>
            </div>
          </div>
          {hits ? (
            hits.length ? (
              <ul className="stack stack--sm" role="list" aria-label="Matching venues">
                {hits.map((h) => (
                  <li key={h.mbid} className="qr-item">
                    <div className="qr-item__top">
                      <div>
                        <strong>{h.name}</strong>
                        <span className="meta">
                          {[h.area, h.address, h.kind].filter(Boolean).join(" · ")}
                        </span>
                      </div>
                      <button className="btn btn--sm btn--primary" type="button" onClick={() => void choose(h)} disabled={busy}>
                        Use this venue
                      </button>
                    </div>
                  </li>
                ))}
              </ul>
            ) : (
              <p className="meta">No venue by that name in the public listings. Try a shorter name.</p>
            )
          ) : null}
        </form>
      ) : null}

      {working && lineup ? (
        <div className="res-status" role="status">
          <span className="spin" aria-hidden="true" />
          Reading public lineups for {lineup.place.name}
          {lineup.progress.events != null
            ? `: ${lineup.progress.events} events, ${lineup.progress.performers ?? 0} acts, matching them to Qloo…`
            : "…"}
        </div>
      ) : null}

      {lineup?.status === "failed" ? (
        <Notice tone="error">
          <strong>That didn&rsquo;t work.</strong>
          {lineup.error ?? "The public source did not answer."} It will try again by itself.
        </Notice>
      ) : null}

      {r && lineup ? (
        <div className="stack">
          <div className="lbl-set">
            <Label kind="measured" detail={`${r.events.used} events${r.events.first ? `, ${year(r.events.first)} to ${year(r.events.last)}` : ""}`} />
            <Label kind="observed" detail={`${r.performers.resolved} of ${r.performers.unique} acts matched in Qloo`} />
          </div>
          <p>
            <strong>
              {lineup.place.name}
              {lineup.place.area ? `, ${lineup.place.area}` : ""}
            </strong>{" "}
            <span className="meta">Source: MusicBrainz (public domain).</span>
          </p>
          {r.state === "insufficient" ? (
            <Notice tone="warn">
              <strong>Not enough public data yet.</strong>
              {r.reason}
            </Notice>
          ) : (
            <>
              <div className="grid-2">
                <div className="stack stack--sm">
                  <h3 className="eyebrow">Acts that play here most</h3>
                  <ul className="legend-list" role="list">
                    {r.top_acts.slice(0, 8).map((a) => (
                      <li key={a.mbid}>
                        <span aria-hidden="true" />
                        <span>
                          {a.name}
                          {a.entity_id ? null : <span className="meta"> · not in Qloo</span>}
                        </span>
                        <span className="num">{a.events}×</span>
                      </li>
                    ))}
                  </ul>
                </div>
                <div className="stack stack--sm">
                  <h3 className="eyebrow">What the room books</h3>
                  <ul className="legend-list" role="list">
                    {r.top_tags.slice(0, 8).map((t) => (
                      <li key={t.tag_id}>
                        <span aria-hidden="true" />
                        <span>{t.name}</span>
                        <span className="num">{Math.round(t.share * 100)}% of acts</span>
                      </li>
                    ))}
                  </ul>
                  {r.top_feel.length ? (
                    <p className="meta">
                      Feel: {r.top_feel.slice(0, 5).map((t) => t.name).join(", ")}.
                    </p>
                  ) : null}
                </div>
              </div>
              {r.groups && r.groups.tribes.length ? (
                <div className="stack stack--sm">
                  <h3 className="eyebrow">Acts that play together</h3>
                  <ul className="stack stack--sm" role="list">
                    {r.groups.tribes.filter((g) => g.shown).map((g, i) => (
                      <li key={g.label + i}>
                        <strong>{g.label}</strong> <span className="meta">about {Math.round(g.share * 100)}% of nights</span>
                        <br />
                        <span className="meta">
                          {g.top_tags.slice(0, 3).map((t) => t.name).join(", ")}. Includes {g.top_items.slice(0, 3).map((x) => x.name).join(", ")}.
                        </span>
                      </li>
                    ))}
                  </ul>
                </div>
              ) : null}
              <p className="meta">
                Only exact matches count: an act Qloo does not hold by the same name or MusicBrainz id is left out, never
                swapped for a similar one.{" "}
                {r.performers.rate < 0.6 ? "Smaller rooms often book local acts Qloo does not know, so this view is partial." : ""}
              </p>
            </>
          )}
        </div>
      ) : null}

      {lineup && canWrite ? (
        <div className="row row--wrap">
          <button className="btn btn--sm btn--ghost" type="button" onClick={() => void remove()} disabled={busy}>
            <Icon name="trash" size="sm" />
            Remove this and choose another
          </button>
        </div>
      ) : null}
    </section>
  );
}
