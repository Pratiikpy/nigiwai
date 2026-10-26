"use client";

import { useEffect, useState } from "react";
import { Icon } from "@/components/Icon";
import { Label } from "@/components/Label";
import { Loading, Notice, PageHead } from "@/components/owner/ui";
import { ApiError, api } from "@/lib/api";
import { type DontDo, type SoundAct, type SoundCell, type SoundPlan, planText } from "@/lib/sound";
import type { Suggestions } from "@/lib/soundcheck";

function Acts({ acts, empty, link }: { acts: SoundAct[]; empty: string; link: string }) {
  if (!acts.length) return <p className="meta">{empty}</p>;
  return (
    <ol className="snd-acts">
      {acts.map((a, i) => (
        <li key={a.entity_id} data-testid="act">
          <span className="snd-acts__n" aria-hidden="true">
            {i + 1}
          </span>
          <span className="snd-acts__b">
            <a className="snd-acts__name" href={`${link}?q=${encodeURIComponent(a.name)}`}>
              {a.name}
            </a>
            <span className="meta">
              {a.genres.length ? `${a.genres.join(", ")} · ` : ""}best for {a.best_for}
            </span>
            {a.watch ? (
              <span className="snd-acts__watch" data-testid="watch">
                Watch: ranks low for {a.watch.label}
                {a.watch.share < 1 ? `, ${Math.round(a.watch.share * 100)}% of this stretch` : ""}
              </span>
            ) : null}
          </span>
          <span className="snd-acts__s">
            <strong className="num">{a.score}</strong>
            <span className="sr-only"> out of 100</span>
          </span>
        </li>
      ))}
    </ol>
  );
}

function Cell({ cell, link }: { cell: SoundCell; link: string }) {
  return (
    <article className="card snd-cell" data-testid="cell" data-key={cell.key} data-status={cell.status} aria-labelledby={`c-${cell.key}`}>
      <header className="snd-cell__head">
        <h3 id={`c-${cell.key}`} className="snd-cell__t">
          {cell.part}
        </h3>
        <span className="meta">{cell.hours}</span>
        {cell.busy_label ? (
          <span className="snd-busy" data-level={cell.busy_label} data-testid="busy">
            {cell.busy_label}
          </span>
        ) : null}
      </header>
      {cell.status === "ok" ? (
        <>
          <div className="snd-mix" data-testid="mix">
            <Label kind="measured" />
            <span>
              {cell.mix
                .slice(0, 3)
                .map((m) => `${m.label} ${Math.round(m.share * 100)}%`)
                .join(", ")}
            </span>
          </div>
          <Acts acts={cell.acts} empty="No acts to name here." link={link} />
        </>
      ) : (
        <p className="meta snd-cell__why">{cell.reason}</p>
      )}
    </article>
  );
}

/** PRD M18, shown as what it is: an idea, modelled from the low end of Qloo's rankings, which has not been tested. */
function DontDoPanel({ doc, link }: { doc: DontDo; link: string }) {
  return (
    <details className="disc" data-testid="dont-do" data-state={doc.state}>
      <summary>
        <Icon name="chev-r" />
        Acts to leave off, and stretch picks <Label kind="modelled" detail="idea only" />
      </summary>
      <div className="disc__body stack">
        <p className="meta" data-testid="dont-do-note">
          {doc.note}
        </p>
        {doc.state === "withheld" ? (
          <p data-testid="dont-do-withheld">{doc.reason}</p>
        ) : (
          <>
            <h3 className="snd-sub">Your main groups rank these poorly</h3>
            {doc.leave_off.length ? (
              <ul className="snd-dd" data-testid="leave-off">
                {doc.leave_off.map((a) => (
                  <li key={a.entity_id}>
                    <a href={`${link}?q=${encodeURIComponent(a.name)}`}>{a.name}</a>
                    <span className="meta">
                      {a.genres.length ? `${a.genres.join(", ")} · ` : ""}
                      {a.reason}
                    </span>
                  </li>
                ))}
              </ul>
            ) : (
              <p className="meta" data-testid="leave-off-none">
                None of the {doc.acts_considered} acts scored is ranked below the weak line by one of your main groups ({(doc.main_groups ?? []).join(", ")}).
              </p>
            )}
            <h3 className="snd-sub">Stretch picks</h3>
            {doc.stretch.length ? (
              <ul className="snd-dd" data-testid="stretch">
                {doc.stretch.map((a) => (
                  <li key={a.entity_id}>
                    <a href={`${link}?q=${encodeURIComponent(a.name)}`}>{a.name}</a>
                    <span className="meta">
                      {a.genres.length ? `${a.genres.join(", ")} · ` : ""}
                      {a.reason}
                    </span>
                  </li>
                ))}
              </ul>
            ) : (
              <p className="meta" data-testid="stretch-none">
                No scored act reaches toward a smaller group while staying comfortable for your main ones.
              </p>
            )}
          </>
        )}
      </div>
    </details>
  );
}

/** `soundcheckLink` is where an act is checked: the owner's Soundcheck page, or a demo venue's own page. */
export function SoundWorkspace({ base, canWrite, soundcheckLink = "/app/soundcheck" }: { base: string; canWrite: boolean; soundcheckLink?: string }) {
  const [doc, setDoc] = useState<SoundPlan | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  const [tick, setTick] = useState(0);
  const [building, setBuilding] = useState(false);
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    let live = true;
    api<SoundPlan>(`${base}/sound`)
      .then((d) => live && setDoc(d))
      .catch((e: unknown) => live && setProblem(e instanceof ApiError ? e.detail : "We couldn’t load the Sound plan."));
    return () => {
      live = false;
    };
  }, [base, tick]);

  // while the acts are being scored the page polls the suggestion job it started
  useEffect(() => {
    if (!building) return;
    const timer = setInterval(() => {
      api<Suggestions>(`${base}/suggestions`)
        .then((s) => {
          if (s && (s.status === "ready" || s.status === "failed")) {
            setBuilding(false);
            if (s.status === "failed") setProblem(`The acts could not be scored: ${s.error ?? "unknown reason"}`);
            setTick((n) => n + 1);
          }
        })
        .catch(() => undefined);
    }, 3000);
    return () => clearInterval(timer);
  }, [building, base]);

  const build = () => {
    setProblem(null);
    setBuilding(true);
    api(`${base}/suggestions`, { method: "POST" }).catch((e: unknown) => {
      setBuilding(false);
      setProblem(e instanceof ApiError ? e.detail : "We couldn’t start that.");
    });
  };

  const copy = async () => {
    if (!doc) return;
    try {
      await navigator.clipboard.writeText(planText(doc));
      setCopied(true);
      setTimeout(() => setCopied(false), 2500);
    } catch {
      setProblem("Your browser did not allow copying. Use Print instead.");
    }
  };

  if (!doc && !problem) return <Loading />;
  if (!doc) return <Notice tone="error">{problem}</Notice>;
  const plan = doc.plan;

  return (
    <>
      <PageHead
        title="Sound plan"
        lead="Which acts to play at which time of the week, from who is actually in your room then. Artists, not songs: your own music service supplies the tracks."
      />
      {problem ? <Notice tone="error">{problem}</Notice> : null}

      {doc.state !== "ready" ? (
        <section className="card stack" data-testid="not-ready" data-state={doc.state}>
          <h2 className="card__title">{doc.state === "no_crowd" ? "No crowd to plan for yet" : doc.state === "stale" ? "The acts are out of date" : "Score some acts first"}</h2>
          <p>{doc.reason}</p>
          {doc.can_build && canWrite ? (
            <div className="row row--wrap">
              <button className="btn btn--primary" type="button" onClick={build} disabled={building} data-testid="build">
                <Icon name="refresh" size="sm" />
                {building ? "Scoring acts…" : "Build the acts"}
              </button>
              {building ? <span className="meta">This takes a minute or two. The page updates itself.</span> : null}
            </div>
          ) : null}
        </section>
      ) : null}

      {doc.state === "ready" && plan ? (
        <>
          <p className="meta" data-testid="basis">
            {doc.basis?.label}
            {doc.basis?.provisional ? " · provisional" : ""} · {plan.acts_considered} acts considered
          </p>
          {doc.reason ? <Notice tone="warn">{doc.reason}</Notice> : null}
          {doc.kind === "timed" && plan.cells ? (
            <>
              {[...new Set(plan.cells.map((c) => c.days))].map((days) => (
                <section key={days} className="stack" aria-label={days}>
                  <h2 className="snd-days">{days}</h2>
                  <div className="snd-grid">
                    {plan.cells
                      ?.filter((c) => c.days === days)
                      .map((c) => (
                        <Cell key={c.key} cell={c} link={soundcheckLink} />
                      ))}
                  </div>
                </section>
              ))}
              {doc.has_hours === false ? <Notice tone="warn">Your opening hours are not set, so every stretch is considered. Add them on Your venue so closed hours are left out.</Notice> : null}
            </>
          ) : (
            <section className="card stack" aria-labelledby="h-all">
              <h2 className="card__title" id="h-all">
                Acts for your whole crowd
              </h2>
              <Acts acts={plan.acts ?? []} empty="No acts to name yet." link={soundcheckLink} />
            </section>
          )}
          <div className="row row--wrap">
            <button className="btn" type="button" onClick={() => void copy()}>
              <Icon name="copy" size="sm" />
              {copied ? "Copied" : "Copy as text"}
            </button>
            <button className="btn btn--ghost" type="button" onClick={() => window.print()}>
              Print
            </button>
            {canWrite ? (
              <button className="btn btn--ghost" type="button" onClick={build} disabled={building}>
                <Icon name="refresh" size="sm" />
                {building ? "Scoring acts…" : "Score the acts again"}
              </button>
            ) : null}
          </div>
          {doc.dont_do ? <DontDoPanel doc={doc.dont_do} link={soundcheckLink} /> : null}
          <details className="disc">
            <summary>
              <Icon name="chev-r" />
              How this is worked out
            </summary>
            <div className="disc__body stack">
              <p>{plan.formula}</p>
              <p className="meta">
                For each stretch the share of each group is taken from when its members scanned, and each act is scored with the same formula as Soundcheck using that mix. Weights {plan.version}: a starting design, not calibrated.
              </p>
            </div>
          </details>
        </>
      ) : null}

      <ul className="snd-notes" data-testid="notes">
        {doc.notes.map((n) => (
          <li key={n} className="meta">
            {n}
          </li>
        ))}
      </ul>
    </>
  );
}
