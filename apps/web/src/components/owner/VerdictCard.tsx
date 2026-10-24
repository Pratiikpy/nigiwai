"use client";

import { useState } from "react";
import { Icon } from "@/components/Icon";
import { Label } from "@/components/Label";
import { ApiError, api } from "@/lib/api";
import { WEEKDAY_INITIAL, WEEKDAYS, dayList, type QlooCall, type Verdict } from "@/lib/soundcheck";
import { Feedback } from "./Feedback";
import { Notice } from "./ui";

const pct = (x: number) => Math.round(x * 100);

/** The score, its likely range and the plain statement that it is fit, not a forecast. */
function FitBlock({ v }: { v: Verdict }) {
  if (v.score === null || v.band === null) return <Withheld v={v} />;
  const [lo, hi] = v.band;
  return (
    <div className="fit" role="group" aria-label="Soundcheck">
      <p className="fit__word">Soundcheck{v.provisional ? " · provisional" : ""}</p>
      <div className="fit__score">
        <span className="fit__n num" data-testid="score">
          {v.score}
        </span>
        <span className="fit__of">out of 100</span>
      </div>
      <div
        className="fit__range"
        style={{ ["--lo" as string]: lo, ["--hi" as string]: hi, ["--v" as string]: v.score }}
        role="img"
        aria-label={`Fit ${v.score} out of 100, likely range ${lo} to ${hi}`}
      >
        <span className="fit__band" />
        <span className="fit__pin" />
      </div>
      <div className="fit__ticks" aria-hidden="true">
        <span>0</span>
        <span>50</span>
        <span>100</span>
      </div>
      <p className="fit__cap" data-testid="range">
        Likely range {lo} to {hi}. This is fit, not a sales forecast.
      </p>
    </div>
  );
}

function Withheld({ v }: { v: Verdict }) {
  const failed = v.status === "fails_constraint";
  return (
    <div className="fit fit--withheld" role="group" aria-label="Soundcheck">
      <p className="fit__word">Soundcheck</p>
      <div className="hold__why" style={{ display: "flex", gap: 12, alignItems: "flex-start" }}>
        <div className="fit__ring0" aria-hidden="true">
          <Icon name="minus" />
        </div>
        <p data-testid="withheld">
          <strong>{failed ? "It doesn’t fit your venue." : v.status === "unscored" ? "Qloo has no link to score." : "Not enough data yet."}</strong>{" "}
          {v.reason}
        </p>
      </div>
    </div>
  );
}

function Groups({ v }: { v: Verdict }) {
  return (
    <ul className="fit-tribes" aria-label="Fit by group">
      {v.groups.map((g, i) => {
        const score = g.fit === null ? null : pct(g.fit);
        return (
          <li key={g.index} data-t={(i % 3) + 1} data-testid={`group-${g.index}`}>
            <i className="tribe__dot" />
            <span className="name">
              {g.label} <span className="meta">· {pct(g.share) || "–"}% of the crowd</span>
            </span>
            <span className="val">{score ?? "–"}</span>
            <span className="bar" aria-hidden="true">
              <i style={{ ["--v" as string]: score ?? 0 }} />
            </span>
          </li>
        );
      })}
    </ul>
  );
}

function Nights({ v }: { v: Verdict }) {
  if (!v.nights) return null;
  const on = (d: number) => (v.suits.includes(d) ? 2 : (v.nights?.[d] ?? 0) >= 0.3 ? 1 : 0);
  return (
    <div>
      <h3 className="eyebrow" style={{ marginBottom: 8 }}>
        Nights it suits
      </h3>
      <div
        className="dayrow"
        role="img"
        aria-label={v.suits.length ? `Nights it suits: ${dayList(v.suits)}` : "No night stands out"}
      >
        {WEEKDAY_INITIAL.map((d, i) => (
          <span key={WEEKDAYS[i]} data-on={on(i)}>
            {d}
          </span>
        ))}
      </div>
      <p className="meta" style={{ marginTop: 6 }}>
        {v.crowd.kind === "guests" ? "From your scan times and where your groups scan most." : "From the weekday pattern of past events at this venue."}{" "}
        <Label kind="modelled" />
      </p>
    </div>
  );
}

function Working({ v }: { v: Verdict }) {
  const w = v.weights as Record<string, number>;
  const c = v.components;
  const rows: [string, string, string, "modelled" | "observed", string][] = [
    [
      "Group fit",
      `weight ${v.peer_used ? pct(w.group_fit ?? 0.8) : 100}%`,
      c.group_fit === null ? "–" : c.group_fit.toFixed(2),
      "modelled",
      `Share-weighted across the groups: ${v.groups
        .filter((g) => g.status === "scored")
        .map((g) => `${g.label} ${pct(g.share)}%`)
        .join(", ")}. Each group’s figure is the act’s rank among up to ${Math.max(0, ...v.groups.map((g) => g.references))} reference acts Qloo returned for that group.`,
    ],
    [
      "Peer evidence",
      v.peer_used ? `weight ${pct(w.peer ?? 0.2)}%` : "omitted",
      c.peer === null ? "–" : c.peer.toFixed(2),
      "observed",
      v.peer_used ? "Share of nearby venues that book this style." : "No data on what similar venues nearby book, so it carries no weight and the group fit takes its place.",
    ],
    [
      "Clash risk",
      `reduces up to ${pct(w.risk ?? 0.5)}%`,
      c.risk === null ? "–" : c.risk.toFixed(2),
      "modelled",
      `Weight of the crowd the act ranks below ${w.risk_floor ?? 0.5} for.`,
    ],
  ];
  return (
    <details className="disc">
      <summary>
        <Icon name="chev-r" />
        Show the working
      </summary>
      <div className="disc__body">
        <dl className="parts">
          {rows.map(([name, weight, value, kind, why]) => (
            <div key={name}>
              <dt>
                {name} <span className="meta">{weight}</span>
              </dt>
              <dd>{value}</dd>
              <dd className="parts__why">
                <Label kind={kind} /> {why}
              </dd>
            </div>
          ))}
        </dl>
        <pre className="formula" tabIndex={0}>
          {v.formula}
        </pre>
        <p>
          The same inputs always give the same score. Weights {v.weights_version} are a starting design, not calibrated against outcomes. The range
          comes from 200 resamplings seeded by the input fingerprint <span className="mono">{v.input_hash.slice(0, 12)}</span>.
        </p>
      </div>
    </details>
  );
}

function Calls({ v, base }: { v: Verdict; base: string }) {
  const [calls, setCalls] = useState<QlooCall[] | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  const load = async (open: boolean) => {
    if (!open || calls || problem) return;
    try {
      setCalls(await api<QlooCall[]>(`${base}/soundchecks/${v.id}/calls`));
    } catch (e) {
      setProblem(e instanceof ApiError ? e.detail : "We couldn’t load the calls.");
    }
  };
  return (
    <details className="disc" onToggle={(e) => void load((e.currentTarget as HTMLDetailsElement).open)}>
      <summary>
        <Icon name="chev-r" />
        The Qloo calls behind this score
      </summary>
      <div className="disc__body">
        {problem ? <Notice tone="error">{problem}</Notice> : null}
        {!calls && !problem ? <p className="meta">Loading…</p> : null}
        {calls && calls.length === 0 ? <p className="meta">No Qloo call was needed for this answer.</p> : null}
        {calls && calls.length ? (
          <ul className="calls" data-testid="calls">
            {calls.map((c, i) => {
              const sent = Object.fromEntries(c.params);
              const compared = (sent["filter.results.entities"] ?? "").split(",").filter(Boolean).length;
              const seeds = (sent["signal.interests.entities"] ?? "").split(",").filter(Boolean).length;
              return (
                <li key={c.id}>
                  {i + 1}. {c.endpoint} for one group: {seeds} favourite acts as the signal, {compared} acts compared → {c.status}, {c.results}{" "}
                  {c.results === 1 ? "result" : "results"}, {c.cache === "miss" ? `${c.latency_ms} ms` : "from cache"}
                  <details className="disc">
                    <summary>
                      <Icon name="chev-r" />
                      What was sent
                    </summary>
                    <div className="disc__body">
                      <code className="mono">{c.params.map(([k, val]) => `${k}=${val}`).join("&")}</code>
                      {c.rules.length ? (
                        <ul>
                          {c.rules.map((r) => (
                            <li key={r.rule + r.detail}>
                              {r.rule} {r.effect}: {r.detail}
                            </li>
                          ))}
                        </ul>
                      ) : null}
                    </div>
                  </details>
                </li>
              );
            })}
          </ul>
        ) : null}
        <p className="meta">Parameters are shown without the key. Results are cached privately and never published.</p>
      </div>
    </details>
  );
}

function Constraints({ v }: { v: Verdict }) {
  if (!v.constraints.length) return null;
  return (
    <div>
      <h3 className="eyebrow" style={{ marginBottom: 8 }}>
        Your limits
      </h3>
      <ul className="ticks" data-testid="constraints">
        {v.constraints.map((c) => (
          <li key={c.name}>
            <Icon name={c.status === "pass" ? "check" : c.status === "fail" ? "x" : "minus"} size="sm" />
            <span>
              <strong>{c.name[0]?.toUpperCase() + c.name.slice(1)}</strong>:{" "}
              {c.status === "pass" ? "passes. " : c.status === "fail" ? "fails. " : "not scored. "}
              {c.detail.replace(/\.$/, "")}.
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}

/** One Soundcheck verdict: the score with its range, each group's rank, why it fits, what to watch, the nights and the working. */
export function VerdictCard({ v, base, feedback = true }: { v: Verdict; base: string; feedback?: boolean }) {
  const ok = v.status === "ok";
  return (
    <section className="card result" aria-labelledby="h-res" data-testid="verdict" data-status={v.status}>
      <div className="result__head">
        <div>
          <h2 className="result__name" id="h-res">
            {v.candidate.name}
          </h2>
          <p className="result__sub">
            {[v.candidate.genres.slice(0, 3).join(", "), v.candidate.year ? `since ${v.candidate.year}` : null].filter(Boolean).join(" · ") ||
              "An act Qloo knows"}
          </p>
          {v.candidate.description ? <p className="result__sub">{v.candidate.description}</p> : null}
        </div>
        <div className="row row--wrap">
          <span className="vmark">
            <Icon name="check" />
            Real entity in Qloo
          </span>
          <Label kind="modelled" detail={v.crowd.kind === "guests" ? `n = ${v.crowd.n}` : "provisional"} />
        </div>
      </div>

      {v.played_here ? (
        <p className="meta">Played here {v.played_here} {v.played_here === 1 ? "time" : "times"} in the public lineups.</p>
      ) : null}

      {ok ? (
        <div className="scgrid">
          <FitBlock v={v} />
          <div>
            <Groups v={v} />
          </div>
        </div>
      ) : (
        <FitBlock v={v} />
      )}

      {v.problems.length ? <Notice tone="warn">{v.problems.join(" ")}</Notice> : null}

      {ok ? (
        <div className="rr">
          <div>
            <h3>Why it fits</h3>
            {v.why.length ? (
              <ul>
                {v.why.map((t) => (
                  <li key={t}>{t}</li>
                ))}
              </ul>
            ) : (
              <p className="meta">No group ranks this act among its strongest matches.</p>
            )}
          </div>
          <div>
            <h3>Watch out for</h3>
            {v.watch.length ? (
              <ul>
                {v.watch.map((t) => (
                  <li key={t}>{t}</li>
                ))}
              </ul>
            ) : (
              <p className="meta">Nothing stands out.</p>
            )}
          </div>
        </div>
      ) : null}

      <Constraints v={v} />
      {ok ? <Nights v={v} /> : null}

      {ok && v.groups.some((g) => g.alone !== null) ? (
        <p className="meta" data-testid="alone">
          What would change it: if your whole crowd were one group the score would be{" "}
          {v.groups
            .filter((g) => g.alone !== null)
            .map((g) => `${g.alone} for ${g.label}`)
            .join(", ")}
          .
        </p>
      ) : null}

      {v.notes.map((n) => (
        <p className="meta" key={n}>
          {n}
        </p>
      ))}

      {ok ? <Working v={v} /> : null}
      <Calls v={v} base={base} />
      {ok && feedback ? <Feedback kind="soundcheck" /> : null}
    </section>
  );
}
