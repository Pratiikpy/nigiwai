"use client";

import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";
import { Icon } from "@/components/Icon";
import { Label } from "@/components/Label";
import { ComparePanel } from "@/components/owner/ComparePanel";
import { VerdictCard } from "@/components/owner/VerdictCard";
import { Loading, Notice, PageHead } from "@/components/owner/ui";
import { ApiError, api } from "@/lib/api";
import type { ActHit, ActSearch, BasisStatus, Recent, Suggestions, Verdict } from "@/lib/soundcheck";

/** The survey picker's empty answer speaks to a guest ("choose something else you love"); an owner searching for an act is
 * told plainly instead. Any other message (a note about Qloo being unavailable, say) is shown as it came. */
function emptyText(message: string | null): string {
  return !message || message.startsWith("No match yet") ? "No artist by that name. Try another spelling." : message;
}

/** The address with this Soundcheck's id set, keeping whatever else it carries (the demo page's tab). */
function withSc(id: string): string {
  const q = new URLSearchParams(window.location.search);
  q.set("sc", id);
  return `?${q.toString()}`;
}

/**
 * Soundcheck for one venue. `base` is the API path of the venue (an owner's own, or a public demo venue's, whose routes
 * mirror it), so the owner's page and the judge-mode page are the same component. A demo can look and can check an act, but
 * it cannot rebuild suggestions or send feedback.
 */
export function SoundcheckWorkspace({ base, canWrite, demo = false }: { base: string; canWrite: boolean; demo?: boolean }) {

  const [basis, setBasis] = useState<BasisStatus | null>(null);
  const [suggestions, setSuggestions] = useState<Suggestions | undefined>(undefined);
  const [recent, setRecent] = useState<Recent>([]);
  const [verdict, setVerdict] = useState<Verdict | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [hits, setHits] = useState<ActSearch | null>(null);
  const [searching, setSearching] = useState(false);
  const [tick, setTick] = useState(0);
  const asked = useRef(false);

  const fail = (e: unknown, fallback: string) => setProblem(e instanceof ApiError ? e.detail : fallback);

  useEffect(() => {
    let live = true;
    Promise.all([
      api<BasisStatus>(`${base}/soundcheck/basis`),
      api<Suggestions>(`${base}/suggestions`),
      api<Recent>(`${base}/soundchecks`),
    ])
      .then(([b, s, r]) => {
        if (!live) return;
        setBasis(b);
        setSuggestions(s);
        setRecent(r);
      })
      .catch((e: unknown) => live && fail(e, "We couldn’t load Soundcheck."));
    return () => {
      live = false;
    };
  }, [base, tick]);

  // A venue with a crowd and no suggestions yet asks for them once; while they build, the page polls.
  const building = suggestions?.status === "queued" || suggestions?.status === "running";
  useEffect(() => {
    if (demo || !basis?.use || suggestions !== null || asked.current || !canWrite) return;
    asked.current = true;
    api(`${base}/suggestions`, { method: "POST" })
      .then(() => setTick((t) => t + 1))
      .catch((e: unknown) => fail(e, "We couldn’t ask for suggestions."));
  }, [base, demo, basis, suggestions, canWrite]);
  useEffect(() => {
    if (!building) return;
    const timer = setInterval(() => setTick((t) => t + 1), 3000);
    return () => clearInterval(timer);
  }, [building]);

  // A verdict can be opened from a link: /app/soundcheck?sc=<id>.
  useEffect(() => {
    const id = new URLSearchParams(window.location.search).get("sc");
    if (!id) return;
    api<Verdict>(`${base}/soundchecks/${id}`)
      .then(setVerdict)
      .catch((e: unknown) => fail(e, "We couldn’t open that Soundcheck."));
  }, [base]);

  useEffect(() => {
    const q = query.trim();
    if (q.length < 2) return;
    const timer = setTimeout(() => {
      setSearching(true);
      api<ActSearch>(`${base}/soundcheck/search?q=${encodeURIComponent(q)}`)
        .then(setHits)
        .catch((e: unknown) => fail(e, "The search didn’t work. Please try again."))
        .finally(() => setSearching(false));
    }, 350);
    return () => clearTimeout(timer);
  }, [query, base]);
  const shownHits = query.trim().length >= 2 ? hits : null;

  const check = useCallback(
    async (hit: Pick<ActHit, "entity_id" | "name">) => {
      setProblem(null);
      setBusy(hit.name);
      setHits(null);
      setQuery("");
      try {
        const v = await api<Verdict>(`${base}/soundcheck`, { method: "POST", body: { entity_id: hit.entity_id } });
        setVerdict(v);
        window.history.replaceState(null, "", withSc(v.id));
        setTick((t) => t + 1);
      } catch (e) {
        fail(e, "That didn’t work. Please try again.");
      } finally {
        setBusy(null);
      }
    },
    [base],
  );

  const open = useCallback(
    async (id: string) => {
      setProblem(null);
      try {
        const v = await api<Verdict>(`${base}/soundchecks/${id}`);
        setVerdict(v);
        window.history.replaceState(null, "", withSc(id));
      } catch (e) {
        fail(e, "We couldn’t open that Soundcheck.");
      }
    },
    [base],
  );

  if (!basis) {
    return problem ? <Notice tone="error">{problem}</Notice> : <Loading />;
  }

  const sug = suggestions?.result;
  return (
    <>
      {demo ? null : (
        <PageHead
          title="Soundcheck"
          lead="Before you book: how well does an act fit the crowd you actually have? The score is computed in code from what Qloo says about each of your groups, and every step is open."
        />
      )}

      {basis.use === "lineup" && basis.lineup ? (
        <Notice tone="warn">
          <strong>Modelled from public lineups.</strong>
          {basis.lineup.events} events at {basis.lineup.place}, {basis.lineup.acts} acts matched in Qloo. Groups are scenes found in who plays there, not your
          guests, and the score is provisional.{demo ? "" : " "}
          {demo ? null : <Link href="/app/people">Add your own guests</Link>}
          {demo ? null : " to replace it."}
        </Notice>
      ) : null}
      {basis.use === "guests" && basis.guests ? (
        <Notice tone="ok">
          Checked against your <strong>{basis.guests.n} guests</strong> in {basis.guests.groups} groups
          {basis.guests.state === "provisional" ? " (provisional until 200 guests)" : ""}.
        </Notice>
      ) : null}
      {basis.use === null ? (
        <Notice tone="warn">
          <strong>There is no crowd to check against yet.</strong>
          {basis.lineup?.needs_refresh
            ? " Your public lineup was built before Soundcheck existed: rebuild it on My people."
            : " Collect 60 guests with your poster, or start from public lineups."}{" "}
          {demo ? null : <Link href="/app/people">Open My people</Link>}
        </Notice>
      ) : null}
      {problem ? <Notice tone="error">{problem}</Notice> : null}

      {basis.use ? (
        <section className="card actpick" aria-labelledby="h-pick">
          <h2 className="card__title" id="h-pick">
            Which act are you thinking of booking?
          </h2>
          <form className="search" role="search" onSubmit={(e) => e.preventDefault()}>
            <label className="sr-only" htmlFor="actq">
              Search for an act
            </label>
            <Icon name="search" />
            <input
              className="input"
              id="actq"
              type="search"
              placeholder="Search any artist"
              autoComplete="off"
              maxLength={80}
              value={query}
              onChange={(e) => setQuery(e.target.value)}
            />
          </form>
          {searching ? <Loading label="Searching…" /> : null}
          {shownHits && shownHits.items.length ? (
            <ul className="stack stack--sm" role="list" aria-label="Matching acts">
              {shownHits.items.map((h) => (
                <li key={h.entity_id} className="qr-item">
                  <div className="qr-item__top">
                    <div>
                      <strong>{h.name}</strong>
                      <span className="meta">{[h.year, h.description].filter(Boolean).join(" · ")}</span>
                    </div>
                    <button className="btn btn--sm btn--primary" type="button" onClick={() => void check(h)} disabled={busy !== null}>
                      <Icon name="bolt" size="sm" />
                      Soundcheck
                    </button>
                  </div>
                </li>
              ))}
            </ul>
          ) : null}
          {shownHits && !shownHits.items.length && !searching ? <p className="meta">{emptyText(shownHits.message)}</p> : null}

          {building ? <Loading label="Finding acts for your groups…" /> : null}
          {sug && (sug.top.length || sug.wildcard) ? (
            <>
              <div className="actchips" role="group" aria-label="Suggested acts">
                {[...sug.top, ...(sug.wildcard ? [sug.wildcard] : [])].map((s) => (
                  <button
                    key={s.entity_id}
                    className="chipbtn"
                    type="button"
                    aria-pressed={verdict?.candidate.entity_id === s.entity_id}
                    onClick={() => void open(s.soundcheck_id)}
                  >
                    {s.name}
                    <span className="chip__score">{s.score}</span>
                    {sug.wildcard && s.entity_id === sug.wildcard.entity_id ? <span className="wild">Wildcard</span> : null}
                  </button>
                ))}
              </div>
              <p className="meta">
                Suggested from Qloo’s neighbours of your groups’ favourites, each scored the same way.{" "}
                {sug.wildcard
                  ? "The Wildcard is a small act just outside the obvious."
                  : "No Wildcard this time: no small act ranks well for both of your biggest groups."}{" "}
                <Label kind="modelled" />
              </p>
            </>
          ) : null}
          {suggestions?.status === "failed" ? <Notice tone="warn">Suggestions could not be built: {suggestions.error}</Notice> : null}
          {canWrite && !demo && suggestions && !building ? (
            <div className="row row--wrap">
              <button className="btn btn--sm btn--ghost" type="button" onClick={() => api(`${base}/suggestions`, { method: "POST" }).then(() => setTick((t) => t + 1))}>
                <Icon name="refresh" size="sm" />
                Suggest again
              </button>
            </div>
          ) : null}
        </section>
      ) : null}

      {busy ? <Loading label={`Asking Qloo how ${busy} fits each of your groups…`} /> : null}
      {verdict && !busy ? (
        <div className="sc">
          <div className="stack">
            <VerdictCard v={verdict} base={base} feedback={!demo} />
          </div>
          {verdict.status === "ok" ? <ComparePanel key={verdict.id} base={base} soundcheckId={verdict.id} name={verdict.candidate.name} /> : null}
        </div>
      ) : null}

      {recent.length && !demo ? (
        <section className="stack" aria-labelledby="h-recent">
          <h2 id="h-recent">Recent Soundchecks</h2>
          <ul className="stack stack--sm" role="list">
            {recent.map((r) => (
              <li key={r.id}>
                <button className="btn btn--sm btn--ghost" type="button" onClick={() => void open(r.id)}>
                  {r.name}
                  <span className="meta">
                    {r.score === null ? "no score" : r.score} · {new Date(r.created_at).toLocaleDateString()}
                  </span>
                </button>
              </li>
            ))}
          </ul>
        </section>
      ) : null}
    </>
  );
}
