"use client";

import Link from "next/link";
import { type FormEvent, useCallback, useEffect, useRef, useState } from "react";
import { Icon } from "@/components/Icon";
import { QuestionControl } from "@/components/owner/QuestionControl";
import { Loading, Notice, PageHead } from "@/components/owner/ui";
import { ApiError, api } from "@/lib/api";
import type { Confirmed, Interview, OnboardingState, Place, Plan, PlanModule } from "@/lib/onboarding";
import { useVenue } from "@/lib/venue";

function PlanList({
  modules,
  touched,
  onToggle,
  disabled,
}: {
  modules: PlanModule[];
  touched: Record<string, boolean>;
  onToggle: (id: string, on: boolean) => void;
  disabled: boolean;
}) {
  return (
    <ul className="onb-plan" data-testid="plan">
      {modules.map((m) => {
        const on = touched[m.id] ?? m.on;
        const fixed = m.locked || !m.available;
        return (
          <li key={m.id} data-module={m.id} data-on={on}>
            <label className="check onb-plan__switch">
              <input type="checkbox" checked={on} disabled={disabled || fixed} onChange={(e) => onToggle(m.id, e.target.checked)} />
              <span>{m.label}</span>
            </label>
            <p className="onb-plan__why">
              {m.reason}
              {m.locked ? <span className="meta"> Always on.</span> : null}
            </p>
          </li>
        );
      })}
    </ul>
  );
}

function Conversation({ session }: { session: Interview }) {
  // the question being asked is shown in its own card just below, so it is not repeated in the log
  const last = session.messages[session.messages.length - 1];
  const shown = last && last.role === "assistant" && last.field && last.field === session.question?.field ? session.messages.slice(0, -1) : session.messages;
  const end = useRef<HTMLDivElement>(null);
  useEffect(() => {
    end.current?.scrollIntoView({ block: "nearest" });
  }, [shown.length]);
  return (
    <div className="onb-log" role="log" aria-label="Conversation" data-testid="log" tabIndex={0}>
      <ol>
        {shown.map((m, i) => (
          <li key={i} className="onb-msg" data-role={m.role}>
            <span className="sr-only">{m.role === "assistant" ? "Nigiwai: " : "You: "}</span>
            {m.text}
          </li>
        ))}
      </ol>
      <div ref={end} />
    </div>
  );
}

export function OnboardingWorkspace() {
  const { tenantPath, canWrite, reload, venue } = useVenue();
  const [data, setData] = useState<OnboardingState | null>(null);
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  const [editing, setEditing] = useState<string | null>(null);
  const [touched, setTouched] = useState<Record<string, boolean>>({});
  const [switching, setSwitching] = useState<Record<string, boolean>>({});
  const [name, setName] = useState<string | null>(null);
  const [zone, setZone] = useState(() => (typeof Intl !== "undefined" ? Intl.DateTimeFormat().resolvedOptions().timeZone : "UTC") || "UTC");
  const [words, setWords] = useState("");
  const [saved, setSaved] = useState<Confirmed | null>(null);
  const [tick, setTick] = useState(0);

  useEffect(() => {
    if (!tenantPath) return;
    let live = true;
    api<OnboardingState>(`${tenantPath}/onboarding`)
      .then((d) => live && setData(d))
      .catch((e: unknown) => live && setProblem(e instanceof ApiError ? e.detail : "We couldn’t load this page."));
    return () => {
      live = false;
    };
  }, [tenantPath, tick]);

  const session = data?.session ?? null;

  const run = useCallback(
    async (work: () => Promise<void>) => {
      setBusy(true);
      setProblem(null);
      try {
        await work();
      } catch (e) {
        const message = e instanceof ApiError ? e.detail : "That didn’t work. Please try again.";
        setProblem(message);
        if (e instanceof ApiError && e.status === 409) setTick((n) => n + 1);
      } finally {
        setBusy(false);
      }
    },
    [],
  );

  const take = (next: Interview) => setData((d) => (d ? { ...d, session: next } : d));

  const start = (mode: "auto" | "form", restart = false) =>
    run(async () => {
      const next = await api<Interview>(`${tenantPath}/onboarding`, { method: "POST", body: { mode, restart } });
      setSaved(null);
      setTouched({});
      setEditing(null);
      setName(null);
      setData((d) => (d ? { ...d, session: next } : d));
    });

  const answer = (field: string, value: unknown, place?: Place) =>
    run(async () => {
      if (!session) return;
      const next = await api<Interview>(`${tenantPath}/onboarding/${session.id}/answer`, {
        method: "POST",
        body: { field, value, ...(place ? { place } : {}) },
      });
      take(next);
      setEditing(null);
    });

  const skip = (field: string) =>
    run(async () => {
      if (!session) return;
      take(await api<Interview>(`${tenantPath}/onboarding/${session.id}/skip`, { method: "POST", body: { field } }));
    });

  const say = (e: FormEvent) => {
    e.preventDefault();
    const text = words.trim();
    if (!text || !session) return;
    void run(async () => {
      take(await api<Interview>(`${tenantPath}/onboarding/${session.id}/say`, { method: "POST", body: { text } }));
      setWords("");
    });
  };

  const abandon = () =>
    run(async () => {
      if (!session) return;
      await api<void>(`${tenantPath}/onboarding/${session.id}/abandon`, { method: "POST" });
      setData((d) => (d ? { ...d, session: null } : d));
    });

  const confirm = () =>
    run(async () => {
      if (!session?.plan) return;
      const overrides: Record<string, boolean> = {};
      for (const m of session.plan.modules) {
        const want = touched[m.id];
        if (want !== undefined && want !== m.on) overrides[m.id] = want;
      }
      const done = await api<Confirmed>(`${tenantPath}/onboarding/${session.id}/confirm`, {
        method: "POST",
        body: { name: (name ?? session.business_name ?? "").trim(), timezone: zone.trim() || null, overrides },
      });
      setSaved(done);
      setData((d) => (d ? { ...d, session: null, plan: done.plan } : d));
      await reload();
    });

  const switchModule = (id: string, on: boolean, plan: Plan) => {
    setSwitching((s) => ({ ...s, [id]: on })); // shown at once; the server's answer replaces it
    return run(async () => {
      try {
        const next = await api<Plan>(`${tenantPath}/plan`, { method: "PUT", body: { overrides: { ...plan.overrides, [id]: on } } });
        setData((d) => (d ? { ...d, plan: next } : d));
        await reload();
      } finally {
        setSwitching((s) => Object.fromEntries(Object.entries(s).filter(([k]) => k !== id)));
      }
    });
  };

  if (!data && !problem) return <Loading label="Loading…" />;
  if (!data) return <Notice tone="error">{problem}</Notice>;

  // ---------------------------------------------------------------------------------------------- saved
  if (saved) {
    return (
      <>
        <PageHead title="Saved" lead="Nigiwai is set up for your business. You can change any of this later." />
        <Notice tone="ok">
          <strong>{saved.plan.summary.find((l) => l.field === "type")?.text ?? "Your business"}</strong> is saved. The plan below shows what is switched on and why.
        </Notice>
        <section className="card stack" aria-labelledby="h-saved-plan">
          <h2 className="card__title" id="h-saved-plan">
            Your plan
          </h2>
          <PlanList modules={saved.plan.modules} touched={{}} onToggle={() => undefined} disabled />
          <div className="row row--wrap">
            <Link className="btn btn--primary" href="/app/survey">
              Set up your survey
            </Link>
            <Link className="btn" href="/app/venue">
              Check your venue
            </Link>
            <Link className="btn btn--ghost" href="/app/today">
              Open Today
            </Link>
          </div>
        </section>
      </>
    );
  }

  // ---------------------------------------------------------------------------------------------- the interview
  if (session && session.question) {
    const q = session.question;
    const agent = session.mode === "agent";
    return (
      <>
        <PageHead title="Tell Nigiwai about your business" lead="A few questions, at most eight. You check everything before it is saved." />
        {!canWrite ? <Notice tone="warn">Your role can read this but not answer.</Notice> : null}
        {session.notice ? <Notice tone="warn">{session.notice}</Notice> : null}
        <div className="onb">
          <div className="onb__main">
            <Conversation session={session} />
            <section className="card stack onb-q" aria-labelledby="onb-q-h" data-testid="question" data-field={q.field}>
              <p className="eyebrow" data-testid="progress">
                Question {Math.min(session.asked, session.max_questions)} of at most {session.max_questions}
              </p>
              <h2 className="card__title" id="onb-q-h">
                {q.text}
              </h2>
              <p className="meta">{q.why}</p>
              <fieldset className="onb-fields" disabled={!canWrite || busy}>
                <legend className="sr-only">Your answer</legend>
                <QuestionControl
                  key={q.field}
                  q={q}
                  busy={busy || !canWrite}
                  tenantPath={tenantPath}
                  onAnswer={(value, place) => void answer(q.field, value, place)}
                  onSkip={q.optional ? () => void skip(q.field) : undefined}
                />
              </fieldset>
              {problem ? <Notice tone="error">{problem}</Notice> : null}
              {busy ? <Loading label={agent ? "Reading your answer…" : "Saving…"} /> : null}
            </section>
            {agent ? (
              <form className="card stack" onSubmit={say}>
                <label className="field__label" htmlFor="onb-words">
                  Or tell me about it in your own words
                </label>
                <textarea
                  className="textarea"
                  id="onb-words"
                  rows={3}
                  maxLength={600}
                  placeholder="For example: a small café on Quill Street in Manchester, open eight to five on weekdays."
                  value={words}
                  onChange={(e) => setWords(e.target.value)}
                  disabled={busy || !canWrite}
                />
                <div className="row row--wrap">
                  <button className="btn" type="submit" disabled={busy || !canWrite || !words.trim()}>
                    <Icon name="send" size="sm" />
                    Send
                  </button>
                  <span className="meta">I only record what you say, and you check it at the end.</span>
                </div>
              </form>
            ) : null}
          </div>
          <aside className="onb__side card card--flat stack" aria-labelledby="onb-heard">
            <h2 className="card__title" id="onb-heard" style={{ fontSize: "var(--t-lg)" }}>
              What I have so far
            </h2>
            <dl className="onb-heard" data-testid="heard">
              {session.understood.map((l) => (
                <div key={l.field} data-field={l.field} data-given={l.text !== "Not given" && l.text !== "Not placed yet"}>
                  <dt>{l.label}</dt>
                  <dd>{l.text}</dd>
                </div>
              ))}
            </dl>
            {canWrite ? (
              <button className="btn btn--sm btn--ghost" type="button" onClick={() => void start(session.mode === "agent" ? "auto" : "form", true)} disabled={busy}>
                Start over
              </button>
            ) : null}
          </aside>
        </div>
      </>
    );
  }

  // ---------------------------------------------------------------------------------------------- check and confirm
  if (session && session.ready && session.plan) {
    const fields = session.fields;
    const editQuestion = editing ? (editing === "place" ? fields.area : fields[editing]) : null;
    return (
      <>
        <PageHead title="Here is what I understood" lead="Check it, change anything that is wrong, and choose what to switch on. Nothing is saved until you confirm." />
        {session.notice ? <Notice tone="warn">{session.notice}</Notice> : null}
        <div className="onb onb--confirm">
          <div className="onb__main">
            <section className="card stack" aria-labelledby="h-understood">
              <h2 className="card__title" id="h-understood">
                Your business
              </h2>
              <div className="field">
                <label htmlFor="onb-name">Name</label>
                <input className="input" id="onb-name" maxLength={120} value={name ?? session.business_name ?? ""} onChange={(e) => setName(e.target.value)} disabled={!canWrite} />
              </div>
              <ul className="onb-rows" data-testid="understood">
                {session.understood.map((l) => {
                  const given = l.text !== "Not given" && l.text !== "Not placed yet";
                  return (
                    <li key={l.field} data-field={l.field} data-given={given}>
                      <span className="onb-rows__k">{l.label}</span>
                      <strong className="onb-rows__v">{l.text}</strong>
                      {canWrite ? (
                        <button
                          className="btn btn--sm btn--ghost"
                          type="button"
                          onClick={() => setEditing(editing === l.field ? null : l.field)}
                          aria-expanded={editing === l.field}
                          aria-label={`${given ? "Change" : "Add"} ${l.label.toLowerCase()}`}
                        >
                          {given ? "Change" : "Add"}
                        </button>
                      ) : null}
                    </li>
                  );
                })}
              </ul>
              {editQuestion && editing ? (
                <div className="onb-edit card card--flat stack" data-testid="edit">
                  <h3 className="card__title" style={{ fontSize: "var(--t-lg)" }}>
                    {editQuestion.text}
                  </h3>
                  <QuestionControl
                    key={editing}
                    q={editQuestion}
                    initial={editing === "place" ? session.known.area : session.known[editing]}
                    busy={busy}
                    tenantPath={tenantPath}
                    onAnswer={(value, place) => void answer(editQuestion.field, value, place)}
                    onCancel={() => setEditing(null)}
                  />
                </div>
              ) : null}
              <div className="field">
                <label htmlFor="onb-zone">Time zone</label>
                <input className="input" id="onb-zone" maxLength={64} value={zone} onChange={(e) => setZone(e.target.value)} disabled={!canWrite} aria-describedby="onb-zone-h" />
                <p className="field__hint" id="onb-zone-h">
                  Taken from this browser. It decides which hour each scan is counted in, so use the venue’s own, for example Europe/London.
                </p>
              </div>
            </section>

            <section className="card stack" aria-labelledby="h-plan">
              <h2 className="card__title" id="h-plan">
                What I would switch on, and why
              </h2>
              <PlanList modules={session.plan.modules} touched={touched} onToggle={(id, on) => setTouched((t) => ({ ...t, [id]: on }))} disabled={!canWrite || busy} />
            </section>

            {problem ? <Notice tone="error">{problem}</Notice> : null}
            {canWrite ? (
              <div className="row row--wrap">
                <button className="btn btn--primary btn--lg" type="button" onClick={() => void confirm()} disabled={busy || !(name ?? session.business_name ?? "").trim()} data-testid="confirm">
                  {busy ? "Saving…" : venue?.business ? "Confirm and update" : "Confirm and save"}
                </button>
                <button className="btn btn--ghost" type="button" onClick={() => void abandon()} disabled={busy}>
                  Leave without saving
                </button>
              </div>
            ) : null}
          </div>
        </div>
      </>
    );
  }

  // ---------------------------------------------------------------------------------------------- already set up
  if (data.plan) {
    const plan = data.plan;
    return (
      <>
        <PageHead title="Your plan" lead="What Nigiwai understood about your business, and which tools are switched on for it." />
        {problem ? <Notice tone="error">{problem}</Notice> : null}
        <div className="onb onb--confirm">
          <div className="onb__main">
            <section className="card stack" aria-labelledby="h-summary">
              <h2 className="card__title" id="h-summary">
                Your business
              </h2>
              <dl className="onb-understood" data-testid="summary">
                {plan.summary.map((l) => (
                  <div key={l.field} data-field={l.field}>
                    <dt>{l.label}</dt>
                    <dd>{l.text}</dd>
                  </div>
                ))}
              </dl>
              {canWrite ? (
                <div>
                  <button className="btn" type="button" onClick={() => void start("form")} disabled={busy} data-testid="update">
                    Change what I told you
                  </button>
                </div>
              ) : null}
            </section>
            <section className="card stack" aria-labelledby="h-modules">
              <h2 className="card__title" id="h-modules">
                What is switched on
              </h2>
              <PlanList modules={plan.modules} touched={switching} onToggle={(id, on) => void switchModule(id, on, plan)} disabled={!canWrite} />
              <p className="meta">Version {plan.version} of the plan, confirmed {new Date(plan.confirmed_at).toLocaleDateString()}. Switching a tool off hides it from the menu; nothing is deleted.</p>
            </section>
          </div>
        </div>
      </>
    );
  }

  // ---------------------------------------------------------------------------------------------- not started
  return (
    <>
      <PageHead title="Tell Nigiwai about your business" lead="Answer a few questions and Nigiwai chooses the tools that fit, and says why. It takes about two minutes." />
      {!canWrite ? <Notice tone="warn">Your role can read this but not start it.</Notice> : null}
      {problem ? <Notice tone="error">{problem}</Notice> : null}
      <section className="card stack" aria-labelledby="h-begin">
        <h2 className="card__title" id="h-begin">
          What to expect
        </h2>
        <ul className="onb-expect">
          <li>
            <Icon name="check" />
            At most eight questions, and you can skip the optional ones.
          </li>
          <li>
            <Icon name="check" />
            You see what was understood, and change anything, before it is saved.
          </li>
          <li>
            <Icon name="check" />
            {data.agent_available ? "You can answer one at a time or just write about your business." : "No account details, and nothing about your guests, is asked."}
          </li>
        </ul>
        <div className="row row--wrap">
          <button className="btn btn--primary btn--lg" type="button" onClick={() => void start("auto")} disabled={busy || !canWrite} data-testid="start">
            {busy ? "Starting…" : "Start"}
          </button>
          {data.agent_available ? (
            <button className="btn" type="button" onClick={() => void start("form")} disabled={busy || !canWrite}>
              Use the fixed questions instead
            </button>
          ) : null}
        </div>
      </section>
    </>
  );
}
