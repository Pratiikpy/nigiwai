"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { Icon } from "@/components/Icon";
import { Label } from "@/components/Label";
import { Loading, Notice, PageHead } from "@/components/owner/ui";
import { ApiError, api } from "@/lib/api";
import { type Board, type BoardAction, WEEKDAYS, WEEKDAY_SHORT, lastScanText, sinceText } from "@/lib/today";
import { useVenue } from "@/lib/venue";

function Meter({ v, max, label }: { v: number; max: number; label: string }) {
  return (
    <div className="stat__meterrow">
      <div className="meter" style={{ ["--v" as string]: v, ["--max" as string]: max }} role="img" aria-label={label}>
        <i />
      </div>
      <span className="notenough__n">
        {v} of {max}
      </span>
    </div>
  );
}

function Status({ board }: { board: Board }) {
  const s = board.status;
  const since = sinceText(s.since);
  return (
    <section className="card card--flat status" aria-label="Where your data stands" data-testid="status">
      <div className="stat">
        <span className="stat__n" data-testid="scans">
          {s.scans}
        </span>
        <span className="stat__l">{since ? `scans since ${since}` : "scans so far"}</span>
        <Label kind="measured" />
      </div>
      <div className="stat">
        <span className="stat__n">{s.basis === "guests" ? "Guests" : s.basis === "lineup" ? "Lineups" : "None"}</span>
        <span className="stat__l">{s.basis === "lineup" ? "what your crowd is read from, for now" : s.basis === "guests" ? "what your crowd is read from" : "no crowd to read yet"}</span>
        {s.basis === "lineup" ? <Label kind="modelled" detail="public lineups" /> : null}
      </div>
      <div className="stat">
        <span className="stat__n">{lastScanText(s.last_scan_days)}</span>
        <span className="stat__l">when the last scan came</span>
      </div>
      {s.unlock ? (
        <div className="stat stat--wide">
          <span className="stat__l">
            <strong>{s.unlock.title}</strong>
          </span>
          <Meter v={s.unlock.v} max={s.unlock.max} label={`${s.unlock.v} of ${s.unlock.max} scans`} />
          <span className="stat__l">{s.unlock.text}</span>
        </div>
      ) : null}
    </section>
  );
}

function FitBox({ action }: { action: BoardAction }) {
  const fit = action.fit;
  if (!fit || fit.score === null) return null;
  const [lo, hi] = fit.band ?? [fit.score, fit.score];
  return (
    <div className="fitbox" data-testid="fit">
      <div className="fit" role="group" aria-label="Soundcheck">
        <p className="fit__word">Soundcheck{fit.provisional ? " · provisional" : ""}</p>
        <div className="fit__score">
          <span className="fit__n num">{fit.score}</span>
          <span className="fit__of">out of 100</span>
        </div>
        <div
          className="fit__range"
          style={{ ["--lo" as string]: lo, ["--hi" as string]: hi, ["--v" as string]: fit.score }}
          role="img"
          aria-label={`Fit ${fit.score} out of 100, likely range ${lo} to ${hi}`}
        >
          <span className="fit__band" />
          <span className="fit__pin" />
        </div>
        <p className="fit__cap">Likely range {lo} to {hi}. This is fit, not a sales forecast.</p>
      </div>
      <ul className="fit-tribes" aria-label="Fit by group">
        {fit.groups.map((g, i) => (
          <li key={g.label} data-t={(i % 3) + 1}>
            <i className="tribe__dot" />
            <span className="name">{g.label}</span>
            <span className="val">{Math.round(g.fit * 100)}</span>
            <span className="bar" aria-hidden="true">
              <i style={{ ["--v" as string]: Math.round(g.fit * 100) }} />
            </span>
          </li>
        ))}
      </ul>
      <Label kind="modelled" />
      <Link className="btn btn--sm btn--ghost" href={`/app/soundcheck?sc=${fit.soundcheck_id}`}>
        Open the working
      </Link>
    </div>
  );
}

function ActionCard({
  action,
  index,
  total,
  canWrite,
  busy,
  onDecide,
  onLog,
}: {
  action: BoardAction;
  index: number;
  total: number;
  canWrite: boolean;
  busy: boolean;
  onDecide: (key: string, state: "accepted" | "dismissed" | null) => void;
  onLog: (key: string) => void;
}) {
  if (action.decision === "dismissed") {
    return (
      <article className="card card--tight action" data-testid="action" data-state="dismissed">
        <div className="dismissed">
          <p>
            <strong>Dismissed:</strong> {action.title}
          </p>
          {canWrite ? (
            <button className="btn btn--sm" type="button" disabled={busy} onClick={() => onDecide(action.key, null)}>
              Undo
            </button>
          ) : null}
        </div>
      </article>
    );
  }
  const accepted = action.decision === "accepted";
  return (
    <article className={`card action${accepted ? " is-accepted" : ""}`} aria-labelledby={`t-${index}`} data-testid="action" data-state={accepted ? "accepted" : "open"}>
      <div className="action__top">
        <span className="eyebrow kind">
          <Icon name={action.icon} />
          {action.kind}
        </span>
        <span className="action__n">
          {index + 1} of {total}
        </span>
      </div>
      <h2 className="action__title" id={`t-${index}`}>
        {action.title}
      </h2>
      <div className="action__grid">
        <div className="action__main">
          <p className="action__why">{action.why}</p>
          <ul className="evid" aria-label="Evidence">
            {action.evidence.map((e, i) => (
              <li key={i}>
                <Label kind={e.label} />
                <p>
                  {e.text}
                  {e.note ? <span className="meta">{e.note}</span> : null}
                </p>
              </li>
            ))}
          </ul>
          <div className="prov">
            {action.prov.map((p) => (
              <span key={p}>{p}</span>
            ))}
          </div>
        </div>
        <FitBox action={action} />
      </div>
      {canWrite && !accepted ? (
        <div className="action__foot">
          <button className="btn btn--primary" type="button" disabled={busy} onClick={() => onDecide(action.key, "accepted")}>
            <Icon name="check" />
            Accept
          </button>
          <button className="btn" type="button" disabled={busy} onClick={() => onDecide(action.key, "dismissed")}>
            Not now
          </button>
          <Link className="btn btn--ghost" href={`/app/soundcheck${action.act.soundcheck_id ? `?sc=${action.act.soundcheck_id}` : ""}`}>
            <Icon name="bolt" />
            Soundcheck this act
          </Link>
          <Link className="btn btn--ghost" href={`/app/ask?mode=crowd&q=${encodeURIComponent(`Would ${action.act.name} suit my crowd, and would it clash with anyone?`)}`}>
            <Icon name="chat" />
            Ask Nigiwai about this
          </Link>
        </div>
      ) : null}
      {accepted ? (
        <div className="accepted" style={{ display: "grid" }}>
          <p>
            <Icon name="check" />
            <span>
              <strong>Accepted.</strong> {action.logged ? "Logged as a move, so scans before and after can be compared." : "Log it as a move so Nigiwai can compare scans before and after."}
            </span>
          </p>
          {canWrite ? (
            <div className="row row--wrap">
              <button className={`btn btn--sm${action.logged ? "" : " btn--primary"}`} type="button" disabled={busy || action.logged} onClick={() => onLog(action.key)}>
                {action.logged ? "Logged as a move" : "Log this move"}
              </button>
              {action.logged ? (
                <Link className="btn btn--sm" href="/app/moves">
                  See it on Moves
                </Link>
              ) : null}
              {action.act ? (
                <Link className="btn btn--sm" href={`/app/drafts?action=${encodeURIComponent(action.key)}`}>
                  Prepare drafts
                </Link>
              ) : null}
              <button className="btn btn--sm btn--ghost" type="button" disabled={busy} onClick={() => onDecide(action.key, null)}>
                Undo
              </button>
            </div>
          ) : null}
        </div>
      ) : null}
    </article>
  );
}

function Hours({ board }: { board: Board }) {
  const h = board.hours;
  const quietSet = new Set<string>();
  for (const w of h.quiet) for (let x = w.start; x < w.end; x++) quietSet.add(`${w.weekday}-${x}`);
  const from = h.from ?? 0;
  const to = h.to ?? 0;
  return (
    <section className="card hours-card" aria-labelledby="h-hours" data-testid="hours">
      <div className="card__head" style={{ marginBottom: 0 }}>
        <h2 className="card__title" id="h-hours">
          Your quietest hours
        </h2>
        <Label kind="measured" detail={`n = ${h.scans_in_hours}`} />
      </div>
      {!h.set ? (
        <Notice tone="warn">
          <strong>Say when you are open.</strong> Without your opening hours a quiet hour cannot be told from a closed one.{" "}
          <Link href="/app/venue">Add them on Your venue</Link>.
        </Notice>
      ) : !h.picture ? (
        <p className="meta">
          Your first quiet-hours picture appears at 10 scans. You have {board.status.scans}.
        </p>
      ) : (
        <>
          {h.early ? (
            <Notice tone="warn">
              <strong>Early look.</strong> With {h.scans_in_hours} scans in your opening hours, gaps may be chance. Treat this as a hint, not a pattern.
            </Notice>
          ) : null}
          <table className="hours">
            <caption className="sr-only">Scans by weekday and opening hour</caption>
            <thead>
              <tr>
                <th scope="col">
                  <span className="sr-only">Day</span>
                </th>
                {Array.from({ length: to - from }, (_, i) => from + i).map((hour) => (
                  <th key={hour} scope="col">
                    {hour % 2 === 0 ? hour : <span className="sr-only">{hour}</span>}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {h.cells.map((row, d) => (
                <tr key={d}>
                  <th scope="row">{WEEKDAY_SHORT[d]}</th>
                  {row.map((c, i) => {
                    const hour = from + i;
                    const text = c === null ? "closed" : `${c} ${c === 1 ? "scan" : "scans"}`;
                    return (
                      <td
                        key={hour}
                        {...(c === null ? { "data-closed": "" } : { style: { ["--v" as string]: Math.min(c, 4) } })}
                        className={quietSet.has(`${d}-${hour}`) ? "is-quiet" : undefined}
                      >
                        <span className="sr-only">
                          {WEEKDAYS[d]} {hour}:00, {text}
                        </span>
                      </td>
                    );
                  })}
                </tr>
              ))}
            </tbody>
          </table>
          <div className="hours-key" aria-hidden="true">
            <span>
              <i />0
            </span>
            <span>
              <i className="s1" />1
            </span>
            <span>
              <i className="s3" />3+
            </span>
            <span>
              <i className="q" />
              Quietest
            </span>
            <span>
              <i className="c" />
              Closed
            </span>
          </div>
          {h.quiet.length ? (
            <ol className="quiet-list" aria-label="Quietest three-hour windows" data-testid="quiet">
              {h.quiet.map((w) => (
                <li key={`${w.weekday}-${w.start}`}>
                  <strong>{w.text}</strong>
                  <span className="num">
                    {w.scans} {w.scans === 1 ? "scan" : "scans"}
                  </span>
                </li>
              ))}
            </ol>
          ) : h.early ? null : (
            <p className="meta">No stretch is clearly quieter than the rest. Your scans are spread evenly through your opening hours.</p>
          )}
        </>
      )}
      <p className="meta">Scans are the guests who chose to answer. They are a sample of your visitors, not every visitor.</p>
    </section>
  );
}

function Hold({ board }: { board: Board }) {
  const h = board.hold;
  if (!h) return null;
  return (
    <article className="card action action--hold" aria-labelledby="t-hold" data-testid="hold">
      <div className="action__top">
        <span className="eyebrow kind">
          <Icon name="table" />
          Needs more data
        </span>
      </div>
      <h2 className="action__title" id="t-hold">
        {h.title}
      </h2>
      <div className="hold">
        <div className="hold__why">
          <p className="action__why">
            <strong>Not enough data yet.</strong> {h.why}
          </p>
        </div>
        <div className="stat__meterrow">
          <div className="meter" style={{ ["--v" as string]: h.scans, ["--max" as string]: h.need }} role="img" aria-label={`${h.scans} of ${h.need} scans`}>
            <i />
          </div>
          <span className="notenough__n">
            {h.scans} of {h.need} scans
          </span>
        </div>
        <div>
          <h3 className="eyebrow" style={{ marginBottom: 8 }}>
            What unlocks it
          </h3>
          <ul className="unlock">
            {h.unlock.map((t) => (
              <li key={t}>
                <Icon name="check" />
                {t}
              </li>
            ))}
          </ul>
        </div>
        <div className="row row--wrap">
          <Link className="btn btn--sm" href="/app/posters">
            <Icon name="download" size="sm" />
            Get a table tent
          </Link>
        </div>
      </div>
    </article>
  );
}

function Day0({ board }: { board: Board }) {
  return (
    <section className="card day0" aria-labelledby="h-d0" data-testid="day0">
      <div className="stack">
        <h2 className="display" id="h-d0">
          Your board wakes up with your first scans.
        </h2>
        <p className="muted" style={{ maxWidth: "52ch" }}>
          There is nothing to show yet, and Nigiwai will not guess. This is how to get started.
        </p>
        <ol className="steps">
          <li className="is-done">
            <div>
              <strong>Set up your business</strong>
              <span>{board.venue.business}</span>
            </div>
          </li>
          <li>
            <div>
              <strong>Print the poster and put it where people wait</strong>
              <span>The counter, the queue, the table tents. No staff time needed.</span>
            </div>
          </li>
          <li>
            <div>
              <strong>10 scans: your first quiet-hours picture</strong>
              <span>Which hours are empty. Nothing about individuals.</span>
            </div>
          </li>
          <li>
            <div>
              <strong>60 scans: groups start to form</strong>
              <span>Then your first actions appear here, each with its evidence.</span>
            </div>
          </li>
        </ol>
        <div className="row row--wrap">
          <Link className="btn btn--primary btn--lg" href="/app/posters">
            <Icon name="download" />
            Get the poster
          </Link>
          <Link className="btn btn--lg" href="/app/people">
            Start from public lineups
          </Link>
        </div>
      </div>
    </section>
  );
}

function Thin({ board }: { board: Board }) {
  return (
    <article className="card action action--hold" aria-labelledby="t-thin" data-testid="thin">
      <div className="action__top">
        <span className="eyebrow kind">
          <Icon name="table" />
          Needs more data
        </span>
        <span className="action__n">Today</span>
      </div>
      <h2 className="action__title" id="t-thin">
        Not enough data yet to suggest anything
      </h2>
      <div className="hold">
        <p className="action__why">
          With {board.status.scans} {board.status.scans === 1 ? "scan" : "scans"} and no suggested acts yet, any advice would be a guess. Fit scores stay hidden until there is enough to stand behind them.
        </p>
        <div>
          <h3 className="eyebrow" style={{ marginBottom: 8 }}>
            What would unlock the first action
          </h3>
          <ul className="unlock">
            {board.status.unlock ? (
              <li>
                <Icon name="check" />
                {board.status.unlock.text}
              </li>
            ) : null}
            {!board.hours.set ? (
              <li>
                <Icon name="check" />
                <span>
                  Tell Nigiwai when you are open, on <Link href="/app/venue">Your venue</Link>, so quiet hours can be told from closed ones.
                </span>
              </li>
            ) : null}
            <li>
              <Icon name="check" />
              <span>
                Open <Link href="/app/soundcheck">Soundcheck</Link> so acts are suggested for your crowd.
              </span>
            </li>
          </ul>
        </div>
      </div>
    </article>
  );
}

export function TodayBoard() {
  const { venue, tenantPath, canWrite } = useVenue();
  const businessId = venue?.business?.id;
  const [board, setBoard] = useState<Board | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [tick, setTick] = useState(0);

  useEffect(() => {
    if (!businessId) return;
    let live = true;
    api<Board>(`${tenantPath}/businesses/${businessId}/today`)
      .then((b) => {
        if (!live) return;
        setBoard(b);
        setProblem(null);
      })
      .catch((e: unknown) => live && setProblem(e instanceof ApiError ? e.detail : "We couldn’t load your board."));
    return () => {
      live = false;
    };
  }, [tenantPath, businessId, tick]);

  const act = async (run: () => Promise<unknown>) => {
    setBusy(true);
    try {
      await run();
      setTick((t) => t + 1);
    } catch (e) {
      setProblem(e instanceof ApiError ? e.detail : "That didn’t work. Please try again.");
    } finally {
      setBusy(false);
    }
  };
  const base = `${tenantPath}/businesses/${businessId}/today/actions`;
  const decide = (key: string, state: "accepted" | "dismissed" | null) =>
    act(() => api(`${base}/${encodeURIComponent(key)}`, { method: "PUT", body: { state } }));
  const log = (key: string) => act(() => api(`${base}/${encodeURIComponent(key)}/log`, { method: "POST" }));

  if (!venue) return <Loading />;
  if (!businessId) {
    return (
      <>
        <PageHead title="Today" />
        <Notice tone="warn">
          Set up your venue first, then your week appears here. <Link href="/app/venue">Open Your venue</Link>
        </Notice>
      </>
    );
  }
  if (!board) return problem ? <Notice tone="error">{problem}</Notice> : <Loading label="Reading your week…" />;

  return (
    <>
      <PageHead title="Today" lead={`This week, ${board.week.replace("-W", " week ")}: what is worth doing, and why. Every line says how it was worked out.`} />
      {problem ? <Notice tone="error">{problem}</Notice> : null}
      {board.notes.map((n) => (
        <Notice key={n} tone="warn">
          {n}
        </Notice>
      ))}
      <Status board={board} />
      {board.state === "day0" ? (
        <Day0 board={board} />
      ) : (
        <div className="board">
          <div className="col">
            <div className="actions" aria-label="Actions for this week" data-testid="actions">
              {board.state === "thin" ? <Thin board={board} /> : null}
              {board.actions.map((a, i) => (
                <ActionCard key={a.key} action={a} index={i} total={board.actions.length + (board.hold ? 1 : 0)} canWrite={canWrite} busy={busy} onDecide={decide} onLog={log} />
              ))}
              <Hold board={board} />
            </div>
          </div>
          <div className="col">
            <Hours board={board} />
            <section className="card card--flat" aria-labelledby="h-legend">
              <h2 className="card__title" id="h-legend" style={{ fontSize: "var(--t-lg)", marginBottom: "var(--s-3)" }}>
                How to read the labels
              </h2>
              <ul className="stack stack--sm">
                <li>
                  <Label kind="measured" /> <span className="meta">Counted from your guests’ own scans.</span>
                </li>
                <li>
                  <Label kind="observed" /> <span className="meta">Looked up in Qloo’s data.</span>
                </li>
                <li>
                  <Label kind="modelled" /> <span className="meta">Our inference from the two above: a hypothesis to check, not a fact.</span>
                </li>
              </ul>
            </section>
          </div>
        </div>
      )}
    </>
  );
}
