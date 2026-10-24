"use client";

import { type FormEvent, useCallback, useEffect, useRef, useState } from "react";
import { Icon } from "@/components/Icon";
import { Label } from "@/components/Label";
import { Loading, Notice, PageHead } from "@/components/owner/ui";
import { ApiError, api, postStream } from "@/lib/api";
import { type Answer, type LiveCall, type LiveStep, type Mode, type Past, SUGGESTIONS, type TraceCall, paramsText, provenanceText } from "@/lib/ask";
import { useVenue } from "@/lib/venue";

type Turn = {
  key: string;
  question: string;
  mode: Mode;
  status: "working" | "done" | "error";
  steps: LiveStep[];
  calls: LiveCall[];
  answer: Answer | null;
  error: string | null;
};

function Steps({ turn }: { turn: Turn }) {
  const working = turn.status === "working";
  const qloo = turn.answer?.stats.qloo_calls ?? turn.calls.length;
  return (
    <details className="ask-work" open={working} data-testid="steps">
      <summary>
        <Icon name="chev-r" size="sm" />
        <span>{working ? "Working on it" : `Checked in ${turn.steps.length} ${turn.steps.length === 1 ? "step" : "steps"}, ${qloo} Qloo ${qloo === 1 ? "call" : "calls"}`}</span>
      </summary>
      <ol className="ask-steps" aria-label="Steps">
        {turn.steps.map((s, i) => {
          const last = working && i === turn.steps.length - 1;
          return (
            <li key={i} data-testid="step">
              <span className="ask-steps__i" aria-hidden="true">
                {last ? <span className="spin" /> : <Icon name="check" size="sm" />}
              </span>
              <span>{s.text}</span>
            </li>
          );
        })}
        {working && turn.steps.length === 0 ? (
          <li>
            <span className="ask-steps__i" aria-hidden="true">
              <span className="spin" />
            </span>
            <span>Reading your question</span>
          </li>
        ) : null}
      </ol>
    </details>
  );
}

function AnswerCard({ answer, onTrace }: { answer: Answer; onTrace: (a: Answer) => void }) {
  const kept = answer.items.length;
  const left = answer.rejected.length;
  return (
    <article className="card ask-answer" aria-labelledby={`av-${answer.id}`} data-testid="answer" data-kind={answer.kind}>
      <div className="ask-answer__head">
        <p className="eyebrow">Answer</p>
        {answer.kind === "template" ? <Label kind="observed" detail="what Qloo returned" /> : <Label kind="modelled" />}
      </div>
      <h2 className="ask-verdict" id={`av-${answer.id}`} data-testid="verdict" tabIndex={-1}>
        {answer.verdict}
      </h2>

      {answer.items.length ? (
        <section className="ask-sec" aria-label="Items">
          <h3 className="ask-h">Items</h3>
          <ol className="ask-items" data-testid="items">
            {answer.items.map((it) => (
              <li key={it.entity_id} data-testid="item" data-provenance={it.provenance}>
                <span className="ask-items__n" aria-hidden="true">
                  {it.rank}
                </span>
                <div className="ask-items__b">
                  <p>
                    <strong>{it.name}</strong> <span className="meta">{it.type.replace("_", " ")}</span>
                    {it.detail ? <span className="meta"> · {it.detail}</span> : null}
                  </p>
                  {it.reason ? <p className="ask-items__why">{it.reason}</p> : null}
                  <p className="meta">
                    <Label kind="observed" /> {provenanceText(it.provenance)}
                  </p>
                </div>
              </li>
            ))}
          </ol>
        </section>
      ) : null}

      {answer.evidence.length ? (
        <section className="ask-sec" aria-label="Evidence">
          <h3 className="ask-h">Evidence</h3>
          <ul className="ask-evidence" data-testid="evidence">
            {answer.evidence.map((e, i) => (
              <li key={i}>
                <Label kind={e.label} />
                <p>{e.text}</p>
              </li>
            ))}
          </ul>
        </section>
      ) : null}

      {answer.not_enough_data ? (
        <section className="ask-sec" aria-label="What would unlock this" data-testid="not-enough">
          <h3 className="ask-h">Not enough data yet</h3>
          <p>{answer.not_enough_data.reason}</p>
          {answer.not_enough_data.unlock.length ? (
            <ul className="unlock">
              {answer.not_enough_data.unlock.map((u) => (
                <li key={u}>
                  <Icon name="check" />
                  {u}
                </li>
              ))}
            </ul>
          ) : null}
        </section>
      ) : null}

      {answer.warnings.length ? (
        <Notice tone="warn">
          <strong>Where Qloo is weak here.</strong> {answer.warnings.join(" ")}
        </Notice>
      ) : null}

      {answer.what_would_change.length ? (
        <section className="ask-sec" aria-label="What would change this">
          <h3 className="ask-h">What would change this</h3>
          <ul className="ask-change">
            {answer.what_would_change.map((c) => (
              <li key={c}>
                <Icon name="arrow-r" size="sm" />
                <span>{c}</span>
              </li>
            ))}
          </ul>
        </section>
      ) : null}

      {answer.notes.map((n) => (
        <p key={n} className="meta" data-testid="note">
          {n}
        </p>
      ))}

      <div className="ask-validator" role="note" data-testid="validator">
        <Icon name="shield" />
        <p>
          <strong>Checked.</strong>{" "}
          {kept
            ? `${kept} ${kept === 1 ? "item" : "items"} listed, each returned by a Qloo call during this question.`
            : "Nothing was listed."}
          {left
            ? ` ${left} more the assistant proposed ${left === 1 ? "was" : "were"} left out because no Qloo call returned ${left === 1 ? "it" : "them"}.`
            : ""}{" "}
          A name that no call returned is never shown.
        </p>
      </div>

      <div className="ask-answer__foot">
        <button className="btn btn--sm" type="button" onClick={() => onTrace(answer)} data-testid="trace-button">
          <Icon name="list" size="sm" />
          Qloo trace ({answer.stats.qloo_calls} {answer.stats.qloo_calls === 1 ? "call" : "calls"})
        </button>
      </div>
    </article>
  );
}

function TracePanel({ answer, base, onClose }: { answer: Answer; base: string; onClose: () => void }) {
  const [calls, setCalls] = useState<TraceCall[] | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  useEffect(() => {
    let live = true;
    api<TraceCall[]>(`${base}/ask/${answer.id}/trace`)
      .then((c) => live && setCalls(c))
      .catch((e: unknown) => live && setProblem(e instanceof ApiError ? e.detail : "We couldn’t load the trace."));
    return () => {
      live = false;
    };
  }, [base, answer.id]);
  const cached = calls?.filter((c) => c.cache === "hit").length ?? 0;
  return (
    <aside className="card ask-trace" aria-labelledby="h-trace" data-testid="trace">
      <div className="card__head" style={{ marginBottom: 0 }}>
        <h2 className="card__title" id="h-trace">
          Qloo trace
        </h2>
        <button className="btn btn--sm btn--ghost" type="button" onClick={onClose}>
          Close
        </button>
      </div>
      <p className="meta">Every Qloo call behind this answer: what was sent and how Qloo answered. It lists calls and result counts only.</p>
      {problem ? <Notice tone="error">{problem}</Notice> : null}
      {!calls && !problem ? <Loading label="Loading the calls…" /> : null}
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
                    <code className="mono">{paramsText(c.params)}</code>
                  </div>
                </details>
              </li>
            ))}
          </ol>
        </>
      ) : null}
    </aside>
  );
}

export function AskWorkspace() {
  const { venue, tenantPath, canWrite } = useVenue();
  const businessId = venue?.business?.id;
  const base = `${tenantPath}/businesses/${businessId}`;
  const [mode, setMode] = useState<Mode>("crowd");
  const [turns, setTurns] = useState<Turn[]>([]);
  const [past, setPast] = useState<Past[]>([]);
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  const [unavailable, setUnavailable] = useState<string | null>(null);
  const [trace, setTrace] = useState<Answer | null>(null);
  const [tick, setTick] = useState(0);
  const end = useRef<HTMLDivElement>(null);
  const restored = useRef(false);
  const seq = useRef(0);

  useEffect(() => {
    if (!businessId) return;
    let live = true;
    api<Past[]>(`${base}/ask`)
      .then((p) => live && setPast(p))
      .catch(() => undefined);
    return () => {
      live = false;
    };
  }, [base, businessId, tick]);

  // a refresh restores the answer in the address
  useEffect(() => {
    if (!businessId || restored.current) return;
    restored.current = true;
    const id = new URLSearchParams(window.location.search).get("a");
    if (!id) return;
    api<Answer>(`${base}/ask/${id}`)
      .then((a) => {
        setMode(a.mode);
        setTurns([{ key: a.id, question: a.question, mode: a.mode, status: "done", steps: [], calls: [], answer: a, error: null }]);
      })
      .catch(() => undefined);
  }, [base, businessId]);

  const scroll = () => end.current?.scrollIntoView({ block: "nearest", behavior: "smooth" });

  const patch = useCallback((key: string, change: (t: Turn) => Turn) => setTurns((all) => all.map((t) => (t.key === key ? change(t) : t))), []);

  const submit = async (question: string) => {
    const q = question.trim();
    if (!q || busy) return;
    seq.current += 1;
    const key = `t${seq.current}`;
    setBusy(true);
    setProblem(null);
    setText("");
    setTrace(null);
    setTurns((all) => [...all, { key, question: q, mode, status: "working", steps: [], calls: [], answer: null, error: null }]);
    scroll();
    try {
      await postStream(`${base}/ask`, { question: q, mode }, (name, data) => {
        if (name === "step") patch(key, (t) => ({ ...t, steps: [...t.steps, data as LiveStep] }));
        else if (name === "qloo_call") patch(key, (t) => ({ ...t, calls: [...t.calls, data as LiveCall] }));
        else if (name === "answer") {
          const a = data as Answer;
          patch(key, (t) => ({ ...t, status: "done", answer: a }));
          window.history.replaceState(null, "", `?a=${a.id}`);
        } else if (name === "error") patch(key, (t) => ({ ...t, status: "error", error: (data as { message: string }).message }));
      });
      setTick((n) => n + 1);
    } catch (e) {
      const message = e instanceof ApiError ? e.detail : "That didn’t work. Please try again.";
      if (e instanceof ApiError && e.status === 503) setUnavailable(message);
      setTurns((all) => all.filter((t) => t.key !== key));
      setProblem(message);
      setText(q);
    } finally {
      setBusy(false);
      scroll();
    }
  };

  const onSubmit = (e: FormEvent) => {
    e.preventDefault();
    void submit(text);
  };

  const open = async (id: string) => {
    try {
      const a = await api<Answer>(`${base}/ask/${id}`);
      setMode(a.mode);
      setTrace(null);
      setTurns([{ key: a.id, question: a.question, mode: a.mode, status: "done", steps: [], calls: [], answer: a, error: null }]);
      window.history.replaceState(null, "", `?a=${a.id}`);
    } catch {
      setProblem("We couldn’t open that answer.");
    }
  };

  useEffect(() => {
    const last = turns[turns.length - 1];
    if (last?.status === "done" && last.answer) document.getElementById(`av-${last.answer.id}`)?.focus({ preventScroll: true });
  }, [turns]);

  if (!venue) return <Loading />;
  if (!businessId) {
    return (
      <>
        <PageHead title="Ask Nigiwai" />
        <Notice tone="warn">Set up your venue first, then you can ask about your crowd.</Notice>
      </>
    );
  }

  return (
    <>
      <PageHead
        title="Ask Nigiwai"
        lead="Ask about your crowd, or about taste and culture. Every answer comes from Qloo results and your own data, shows the calls behind it, and says so when there is not enough to go on."
      >
        <div className="seg" role="group" aria-label="What to ask about">
          <button type="button" aria-pressed={mode === "crowd"} onClick={() => setMode("crowd")} disabled={busy}>
            About my crowd
          </button>
          <button type="button" aria-pressed={mode === "culture"} onClick={() => setMode("culture")} disabled={busy}>
            About the culture
          </button>
        </div>
      </PageHead>

      <div className="ask">
        <div className="ask__layout">
          <div className="ask__thread" aria-live="polite" data-testid="thread">
            {turns.length === 0 ? (
              <section className="ask-start" aria-labelledby="h-start">
                <h2 className="display" id="h-start">
                  {mode === "crowd" ? "What do you want to know about your crowd?" : "What do you want to know about taste and culture?"}
                </h2>
                <p className="muted">
                  {mode === "crowd"
                    ? "I read your scans and groups and what Qloo returns, and I show every call. If there is not enough data, I say so."
                    : "This works from day one, before any scans. I use only what Qloo returns, and I show every call behind the answer."}
                </p>
                <div className="ask-sug" role="group" aria-label="Try a question">
                  {SUGGESTIONS[mode].map((s) => (
                    <button key={s} className="ask-sug__b" type="button" onClick={() => void submit(s)} disabled={busy || !canWrite || unavailable !== null}>
                      <span>{s}</span>
                      <Icon name="arrow-r" />
                    </button>
                  ))}
                </div>
              </section>
            ) : null}

            {turns.map((t) => (
              <div className="ask-turn" key={t.key} data-testid="turn" data-status={t.status}>
                <p className="ask-user">{t.question}</p>
                {t.status !== "done" || t.steps.length ? <Steps turn={t} /> : null}
                {t.status === "error" ? <Notice tone="error">{t.error}</Notice> : null}
                {t.answer ? <AnswerCard answer={t.answer} onTrace={setTrace} /> : null}
              </div>
            ))}
            <div ref={end} />
          </div>

          <div className="ask__side">
            {trace ? <TracePanel answer={trace} base={base} onClose={() => setTrace(null)} /> : null}
            {past.length ? (
              <section className="card card--flat" aria-labelledby="h-past">
                <h2 className="card__title" id="h-past" style={{ fontSize: "var(--t-lg)", marginBottom: "var(--s-3)" }}>
                  Earlier questions
                </h2>
                <ul className="stack stack--sm" data-testid="past">
                  {past.slice(0, 8).map((p) => (
                    <li key={p.id}>
                      <button className="ask-past" type="button" onClick={() => void open(p.id)}>
                        <span>{p.question}</span>
                        <span className="meta">{p.mode === "crowd" ? "your crowd" : "the culture"}</span>
                      </button>
                    </li>
                  ))}
                </ul>
              </section>
            ) : null}
          </div>
        </div>

        <form className="ask-composer" onSubmit={onSubmit}>
          {unavailable ? <Notice tone="warn">{unavailable}</Notice> : null}
          {problem && !unavailable ? <Notice tone="error">{problem}</Notice> : null}
          {!canWrite ? <Notice tone="warn">Your role can read answers but not ask new questions.</Notice> : null}
          <div className="ask-composer__box">
            <label className="sr-only" htmlFor="ask-q">
              Your question
            </label>
            <textarea
              className="textarea"
              id="ask-q"
              rows={2}
              maxLength={600}
              placeholder={mode === "crowd" ? "Ask about your crowd" : "Ask about taste and culture"}
              value={text}
              onChange={(e) => setText(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey) {
                  e.preventDefault();
                  void submit(text);
                }
              }}
              disabled={busy || !canWrite || unavailable !== null}
            />
            <button className="btn btn--primary" type="submit" disabled={busy || !text.trim() || !canWrite || unavailable !== null}>
              <Icon name="send" />
              {busy ? "Working…" : "Ask"}
            </button>
          </div>
          <p className="meta">
            {mode === "crowd"
              ? "Answers use only your own data and items Qloo returned. Nothing identifies a guest."
              : "Works from day one. Uses only what Qloo returns, and every answer shows its Qloo calls."}
          </p>
        </form>
      </div>
    </>
  );
}
