"use client";

import { useEffect, useState } from "react";
import { Icon } from "@/components/Icon";
import { Label } from "@/components/Label";
import { Loading, Notice, PageHead } from "@/components/owner/ui";
import { ApiError, api } from "@/lib/api";
import { type GhostSection, type GrowCall, type GrowDoc, type GrowPlace, type GrowRun, type PlaceSection, metres, percent } from "@/lib/grow";

const WHO = { guests: "guests", acts: "acts at your venue" } as const;

function groupName(run: GrowRun, index: number): string {
  return run.groups.find((g) => g.index === index)?.label ?? `Group ${index + 1}`;
}

function Ghosts({ run, link }: { run: GrowRun; link: string }) {
  const g: GhostSection = run.ghosts;
  const who = WHO[g.unit];
  const byGroup = run.groups
    .map((grp) => ({ grp, items: g.items.filter((i) => i.group_index === grp.index) }))
    .filter((x) => x.items.length > 0);
  return (
    <section className="stack" aria-labelledby="h-ghost" data-testid="ghosts" data-status={g.status}>
      <div className="gr-head">
        <h2 id="h-ghost" className="gr-h">
          Who else might come
        </h2>
        <Label kind="modelled" detail="idea to check" />
      </div>
      <p className="meta">
        Tastes that sit right next to each of your groups and that almost none of your {who} has. Each comes with the acts that would draw it.
      </p>
      <p className="meta" data-testid="ghost-check">
        {g.act_similarity === null
          ? "Only one group could be read, so there is nothing to compare it with."
          : `Qloo gave your groups different neighbouring acts: ${percent(g.act_similarity)} in common (it must be at most ${percent(g.limit.similarity_max)} for this to be shown).`}
      </p>
      {g.status !== "ok" ? (
        <Notice tone="warn">{g.reason}</Notice>
      ) : (
        <div className="gr-groups">
          {byGroup.map(({ grp, items }) => (
            <article key={grp.index} className="card gr-group" data-testid="ghost-group" aria-labelledby={`g-${grp.index}`}>
              <h3 id={`g-${grp.index}`} className="gr-group__t">
                {grp.label}
              </h3>
              <ul className="gr-list">
                {items.map((i) => (
                  <li key={i.tag_id} data-testid="ghost">
                    <p className="gr-ghost__t">
                      <strong>{i.tag}</strong>
                      <span className="meta"> sits next to {i.bridges.join(" and ")}</span>
                    </p>
                    <p className="meta" data-testid="ghost-carrying">
                      {i.carrying === null ? `Fewer than ${g.limit.min_group} of your ${who} pick it.` : `${i.carrying} of your ${who} pick it.`} {i.neighbours_with_tag} of Qloo’s neighbouring acts carry it.
                    </p>
                    <ol className="snd-acts" aria-label={`Acts that would draw ${i.tag} fans`}>
                      {i.acts.map((a, n) => (
                        <li key={a.entity_id} data-testid="ghost-act">
                          <span className="snd-acts__n" aria-hidden="true">
                            {n + 1}
                          </span>
                          <span className="snd-acts__b">
                            <a className="snd-acts__name" href={`${link}?q=${encodeURIComponent(a.name)}`}>
                              {a.name}
                            </a>
                            <span className="meta">{a.genres.join(", ")}</span>
                          </span>
                          <span />
                        </li>
                      ))}
                    </ol>
                  </li>
                ))}
              </ul>
            </article>
          ))}
        </div>
      )}
      {g.skipped.length ? (
        <ul className="snd-notes" data-testid="ghost-skipped">
          {g.skipped.map((s) => (
            <li key={s.group_index} className="meta">
              {groupName(run, s.group_index)}: {s.reason}
            </li>
          ))}
        </ul>
      ) : null}
      <details className="disc">
        <summary>
          <Icon name="chev-r" />
          How this is worked out
        </summary>
        <div className="disc__body stack">
          <p>
            For each group, Qloo is asked for the acts closest to its favourites. A genre is a ghost when at least {g.limit.min_acts} of those acts carry it and also carry a genre the group clearly has (at least {percent(g.limit.bridge_share)} of its
            members), when no more than {percent(g.limit.absent_share)} of your {who} carry it, and when it is not just a variant of a genre the group already has. A count under {g.limit.min_group} is never shown as a number.
          </p>
          <p className="meta">The limits are choices, not calibrated. Whether people who like these genres would come, or would like these acts, is not measured here.</p>
        </div>
      </details>
    </section>
  );
}

function PlaceRow({ p }: { p: GrowPlace }) {
  return (
    <li data-testid="place">
      <strong>{p.name}</strong>
      <span className="meta">
        {[metres(p.distance_m), p.address].filter(Boolean).join(" · ")}
      </span>
    </li>
  );
}

function Places({ id, title, lead, section }: { id: string; title: string; lead: string; section: PlaceSection }) {
  const taste = section.mode === "taste";
  return (
    <section className="stack" aria-labelledby={`h-${id}`} data-testid={id} data-status={section.status} data-mode={section.mode ?? ""}>
      <div className="gr-head">
        <h2 id={`h-${id}`} className="gr-h">
          {title}
        </h2>
        {section.status === "ok" ? <Label kind={taste ? "modelled" : "observed"} detail={taste ? "idea to check" : "near you"} /> : null}
      </div>
      <p className="meta">{lead}</p>
      <p data-testid={`${id}-note`}>{section.note}</p>
      {section.status === "ok" ? (
        <p className="meta" data-testid={`${id}-check`}>
          {section.seed_effect === null
            ? "No plain list to compare with."
            : `Giving Qloo your crowd’s taste changed ${percent(section.seed_effect)} of its first ten places (at least ${percent(section.limit.seed_effect_min)} is needed to call a list matched).`}
          {section.similarity !== null ? ` Your groups’ lists had ${percent(section.similarity)} in common (at most ${percent(section.limit.similarity_max)} to be told apart).` : ""}
        </p>
      ) : null}
      {section.status === "ok" && section.by_group ? (
        <div className="gr-groups">
          {section.by_group.map((g) => (
            <article key={g.group_index} className="card gr-group" data-testid={`${id}-group`} aria-labelledby={`${id}-g-${g.group_index}`}>
              <h3 id={`${id}-g-${g.group_index}`} className="gr-group__t">
                {g.group}
              </h3>
              {!g.own ? (
                <p className="gr-gap" data-testid="gap">
                  No place of its own among Qloo’s first ten for this group: a gap candidate. Check on the ground before acting.
                </p>
              ) : null}
              <ul className="gr-list">
                {g.items.map((p) => (
                  <PlaceRow key={p.entity_id} p={p} />
                ))}
              </ul>
            </article>
          ))}
        </div>
      ) : null}
      {section.status === "ok" && !section.by_group ? (
        <article className="card gr-group" aria-label={title}>
          <ul className="gr-list">
            {section.items.map((p) => (
              <PlaceRow key={p.entity_id} p={p} />
            ))}
          </ul>
        </article>
      ) : null}
    </section>
  );
}

function PlacesPartView({ run }: { run: GrowRun }) {
  const places = run.places;
  if (places.status === "unavailable") {
    return (
      <section className="stack" aria-labelledby="h-places" data-testid="places-unavailable">
        <h2 id="h-places" className="gr-h">
          Places
        </h2>
        <Notice tone="warn">{places.reason}</Notice>
      </section>
    );
  }
  return (
    <>
      <Places
        id="nearby"
        title="Who serves your crowd nearby"
        lead={`Open places of your kind within ${metres(places.radius_m)} that Qloo ties to your crowd, as the neighbours your guests may already visit. Possible partners or competition.`}
        section={places.nearby}
      />
      <Places
        id="elsewhere"
        title="Places like yours further out"
        lead={`Places between ${metres(places.radius_m)} and ${metres(places.wide_radius_m)} away that Qloo ties to your crowd. Where else your people may go, and who to look at.`}
        section={places.elsewhere}
      />
      <p className="meta" data-testid="places-foot">
        Qloo says these places are open{places.dropped_closed ? ` (${places.dropped_closed} marked closed ${places.dropped_closed === 1 ? "was" : "were"} left out)` : ""}; that is not independently confirmed
        {places.closure_unanswered ? ", and Qloo could not be asked about some of them" : ""}. Check before you act.
      </p>
    </>
  );
}

function Calls({ base }: { base: string }) {
  const [open, setOpen] = useState(false);
  const [calls, setCalls] = useState<GrowCall[] | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  useEffect(() => {
    if (!open || calls) return;
    let live = true;
    api<GrowCall[]>(`${base}/grow/calls`)
      .then((c) => live && setCalls(c))
      .catch((e: unknown) => live && setProblem(e instanceof ApiError ? e.detail : "We couldn’t load the calls."));
    return () => {
      live = false;
    };
  }, [open, calls, base]);
  const cached = calls?.filter((c) => c.cache === "hit").length ?? 0;
  return (
    <details className="disc" onToggle={(e) => setOpen(e.currentTarget.open)} data-testid="calls-disc">
      <summary>
        <Icon name="chev-r" />
        The Qloo calls behind this
      </summary>
      <div className="disc__body stack">
        <p className="meta">Every call made for the last run: what was sent and how Qloo answered. It lists calls and result counts only; guests’ answers never go to Qloo.</p>
        {problem ? <Notice tone="error">{problem}</Notice> : null}
        {open && !calls && !problem ? <Loading label="Loading the calls…" /> : null}
        {calls ? (
          <>
            <p className="meta">
              {calls.length} {calls.length === 1 ? "call" : "calls"} · {cached} from the private cache
            </p>
            <ol className="calls" data-testid="calls">
              {calls.map((c, i) => (
                <li key={c.id}>
                  {i + 1}. {c.endpoint} for {c.purpose} → {c.status}, {c.results} {c.results === 1 ? "result" : "results"}, {c.cache === "hit" ? "from cache" : `${c.latency_ms} ms`}
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
            </ol>
          </>
        ) : null}
      </div>
    </details>
  );
}

const WAITING = new Set(["queued", "running"]);

export function GrowWorkspace({ base, canWrite, soundcheckLink = "/app/soundcheck" }: { base: string; canWrite: boolean; soundcheckLink?: string }) {
  const [doc, setDoc] = useState<GrowDoc | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  const [tick, setTick] = useState(0);
  const [asking, setAsking] = useState(false);

  useEffect(() => {
    let live = true;
    api<GrowDoc>(`${base}/grow`)
      .then((d) => live && setDoc(d))
      .catch((e: unknown) => live && setProblem(e instanceof ApiError ? e.detail : "We couldn’t load Grow."));
    return () => {
      live = false;
    };
  }, [base, tick]);

  // while the worker is looking things up, the page asks for the stored row until it is done
  const waiting = doc ? WAITING.has(doc.state) : false;
  useEffect(() => {
    if (!waiting) return;
    const timer = setInterval(() => setTick((n) => n + 1), 3000);
    return () => clearInterval(timer);
  }, [waiting]);

  const ask = () => {
    setProblem(null);
    setAsking(true);
    api(`${base}/grow`, { method: "POST" })
      .then(() => setTick((n) => n + 1))
      .catch((e: unknown) => setProblem(e instanceof ApiError ? e.detail : "We couldn’t start that."))
      .finally(() => setAsking(false));
  };

  if (!doc && !problem) return <Loading />;
  if (!doc) return <Notice tone="error">{problem}</Notice>;
  const run = doc.run;
  const showAsk = canWrite && doc.can_build && !waiting;
  const askLabel = doc.state === "not_run" ? "Look things up" : doc.state === "failed" ? "Try again" : "Look things up again";

  return (
    <>
      <PageHead
        title="Grow"
        lead="Who else might come, who already serves your crowd nearby, and places like yours further out. Every finding is an idea to check, read from Qloo and your groups, with the checks that decided what it may claim."
      />
      {problem ? <Notice tone="error">{problem}</Notice> : null}

      {doc.state === "no_crowd" || doc.state === "not_run" || doc.state === "failed" || waiting ? (
        <section className="card stack" data-testid="not-ready" data-state={doc.state}>
          <h2 className="card__title">
            {doc.state === "no_crowd" ? "No crowd to read yet" : waiting ? "Looking things up" : doc.state === "failed" ? "The last look-up did not finish" : "Nothing looked up yet"}
          </h2>
          <p>{doc.reason}</p>
          {waiting ? <Loading label="This takes a minute or two. The page updates itself." /> : null}
          {showAsk ? (
            <div className="row row--wrap">
              <button className="btn btn--primary" type="button" onClick={ask} disabled={asking} data-testid="ask">
                <Icon name="refresh" size="sm" />
                {askLabel}
              </button>
              <span className="meta">About a dozen to twenty-five Qloo calls, once. Opening this page never calls Qloo.</span>
            </div>
          ) : null}
        </section>
      ) : null}

      {run && (doc.state === "ready" || doc.state === "stale") ? (
        <>
          <p className="meta" data-testid="basis">
            {run.basis.label}
            {run.basis.provisional ? " · provisional" : ""} · looked up {new Date(run.generated_at).toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" })}
          </p>
          {doc.state === "stale" ? (
            <Notice tone="warn">
              <span data-testid="stale">{doc.reason}</span>
            </Notice>
          ) : null}
          <Ghosts run={run} link={soundcheckLink} />
          <PlacesPartView run={run} />
          <div className="row row--wrap">
            {showAsk ? (
              <button className="btn btn--ghost" type="button" onClick={ask} disabled={asking} data-testid="ask">
                <Icon name="refresh" size="sm" />
                {askLabel}
              </button>
            ) : null}
          </div>
          <Calls base={base} />
        </>
      ) : null}

      <ul className="snd-notes" data-testid="notes">
        <li className="meta">Nothing on this page is a count of customers. Ghost customers are tastes Qloo finds next to yours; places are what Qloo lists, checked for the closure flag and for the area.</li>
        <li className="meta">Where Qloo’s answer did not change with your crowd’s taste, or gave every group the same places, this page says so and does not claim a match.</li>
        <li className="meta">Whether acting on any of this brings people in is not measured. Log what you try on Moves and compare the scans.</li>
      </ul>
    </>
  );
}
