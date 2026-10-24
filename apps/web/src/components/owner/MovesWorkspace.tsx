"use client";

import { type FormEvent, useEffect, useState } from "react";
import { Icon } from "@/components/Icon";
import { Label } from "@/components/Label";
import { Loading, Notice, PageHead } from "@/components/owner/ui";
import { ApiError, api } from "@/lib/api";
import {
  KIND_LABELS,
  type Move,
  type MoveForm,
  type MoveKind,
  type MovesDoc,
  VERDICT_LABELS,
  emptyForm,
  formOf,
  hourLabel,
  moveBody,
} from "@/lib/moves";
import { DAY_NAMES } from "@/lib/onboarding";

function MoveFormCard({
  form,
  setForm,
  busy,
  onSubmit,
  onCancel,
  editing,
  problem,
}: {
  form: MoveForm;
  setForm: (f: MoveForm) => void;
  busy: boolean;
  onSubmit: (e: FormEvent) => void;
  onCancel: () => void;
  editing: boolean;
  problem: string | null;
}) {
  const set = <K extends keyof MoveForm>(key: K, value: MoveForm[K]) => setForm({ ...form, [key]: value });
  return (
    <form className="card stack" onSubmit={onSubmit} aria-labelledby="mv-form-h" data-testid="move-form" noValidate>
      <h2 className="card__title" id="mv-form-h">
        {editing ? "Change this move" : "Log a move"}
      </h2>
      <div className="grid-2">
        <div className="field">
          <label htmlFor="mv-kind">What kind of change</label>
          <select className="input" id="mv-kind" value={form.kind} onChange={(e) => set("kind", e.target.value as MoveKind)}>
            {(Object.keys(KIND_LABELS) as MoveKind[]).map((k) => (
              <option key={k} value={k}>
                {KIND_LABELS[k]}
              </option>
            ))}
          </select>
        </div>
        <div className="field">
          <label htmlFor="mv-title">What changed</label>
          <input className="input" id="mv-title" maxLength={160} placeholder="Booked The Quiet Engines for Friday evenings" value={form.title} onChange={(e) => set("title", e.target.value)} />
        </div>
      </div>
      <div className="grid-2">
        <div className="field">
          <label htmlFor="mv-start">Started on</label>
          <input className="input" id="mv-start" type="date" value={form.started_on} onChange={(e) => set("started_on", e.target.value)} />
        </div>
        <div className="field">
          <label htmlFor="mv-end">Ended on (leave empty if it is still going)</label>
          <input className="input" id="mv-end" type="date" value={form.ended_on} onChange={(e) => set("ended_on", e.target.value)} />
        </div>
      </div>
      <fieldset className="qset">
        <legend>Which days it was aimed at</legend>
        <div className="chips" role="group" aria-label="Days">
          {DAY_NAMES.map((name, i) => (
            <button
              key={name}
              className="chipbtn chipbtn--sm"
              type="button"
              aria-pressed={form.weekdays.includes(i)}
              onClick={() => set("weekdays", form.weekdays.includes(i) ? form.weekdays.filter((d) => d !== i) : [...form.weekdays, i])}
            >
              {name.slice(0, 3)}
            </button>
          ))}
        </div>
        <p className="field__hint">{form.weekdays.length ? "Only these days are compared." : "None chosen: every day is compared."}</p>
      </fieldset>
      <fieldset className="qset">
        <legend>Which hours</legend>
        <label className="check">
          <input type="checkbox" checked={form.allHours} onChange={(e) => set("allHours", e.target.checked)} />
          <span>All hours you are open</span>
        </label>
        {form.allHours ? null : (
          <div className="row row--wrap">
            <label className="sr-only" htmlFor="mv-from">
              From
            </label>
            <select className="input onb-short" id="mv-from" value={form.hour_from} onChange={(e) => set("hour_from", Number(e.target.value))}>
              {Array.from({ length: 24 }, (_, h) => (
                <option key={h} value={h}>
                  {hourLabel(h)}
                </option>
              ))}
            </select>
            <span aria-hidden="true">to</span>
            <label className="sr-only" htmlFor="mv-to">
              To
            </label>
            <select className="input onb-short" id="mv-to" value={form.hour_to} onChange={(e) => set("hour_to", Number(e.target.value))}>
              {Array.from({ length: 24 }, (_, h) => (
                <option key={h + 1} value={h + 1}>
                  {hourLabel(h + 1)}
                </option>
              ))}
            </select>
          </div>
        )}
      </fieldset>
      <div className="field">
        <label htmlFor="mv-note">A note (optional)</label>
        <input className="input" id="mv-note" maxLength={400} value={form.note} onChange={(e) => set("note", e.target.value)} />
      </div>
      {problem ? <Notice tone="error">{problem}</Notice> : null}
      <div className="row row--wrap">
        <button className="btn btn--primary" type="submit" disabled={busy}>
          {busy ? "Saving…" : editing ? "Save changes" : "Log this move"}
        </button>
        <button className="btn btn--ghost" type="button" onClick={onCancel} disabled={busy}>
          Cancel
        </button>
      </div>
    </form>
  );
}

function MixLine({ title, mix }: { title: string; mix: { scans: number; shown: boolean; groups: { label: string; share: number }[] } }) {
  return (
    <li>
      <span className="meta">{title}</span>
      {mix.shown ? (
        <span>{mix.groups.slice(0, 3).map((g) => `${g.label} ${Math.round(g.share * 100)}%`).join(", ")}</span>
      ) : (
        <span className="meta">Under 10 scans, so no mix is shown.</span>
      )}
    </li>
  );
}

function MoveCard({ move, canWrite, onEdit, onRemove, busy }: { move: Move; canWrite: boolean; onEdit: () => void; onRemove: () => void; busy: boolean }) {
  const [confirming, setConfirming] = useState(false);
  const r = move.result;
  const range = r.rate && r.rate.low !== null ? `${r.rate.low} to ${r.rate.high ?? "no upper limit"}` : null;
  return (
    <article className="card mv" data-testid="move" data-verdict={r.verdict} aria-labelledby={`mv-${move.id}`}>
      <header className="mv__head">
        <div>
          <p className="eyebrow">{KIND_LABELS[move.kind]}</p>
          <h3 className="mv__title" id={`mv-${move.id}`}>
            {move.title}
          </h3>
        </div>
        <span className="mv__verdict" data-verdict={r.verdict} data-testid="verdict">
          {VERDICT_LABELS[r.verdict]}
        </span>
      </header>
      <p className="meta">
        {move.slot.text} · from {move.started_on}
        {move.ended_on ? ` to ${move.ended_on}` : ", still going"}
        {move.source === "today" ? " · logged from Today" : ""}
      </p>
      {move.note ? <p className="mv__note">{move.note}</p> : null}
      <div className="mv__nums" data-testid="numbers">
        <div>
          <Label kind="measured" />
          <p>
            <strong className="num">{r.before.scans}</strong> scans before, over {r.before.days} matching {r.before.days === 1 ? "day" : "days"}
            {r.rate ? ` (${r.rate.before} a day)` : ""}
          </p>
        </div>
        <div>
          <Label kind="measured" />
          <p>
            <strong className="num">{r.after.scans}</strong> scans after, over {r.after.days} matching {r.after.days === 1 ? "day" : "days"}
            {r.rate ? ` (${r.rate.after} a day)` : ""}
          </p>
        </div>
      </div>
      {r.rate && r.rate.ratio !== null ? (
        <p data-testid="ratio">
          {r.rate.ratio}× the rate before, {r.interval} range {range}.
        </p>
      ) : null}
      <p className="mv__text" data-testid="text">
        {r.text}
      </p>
      {r.mix ? (
        <details className="disc">
          <summary>
            <Icon name="chev-r" />
            Who came, before and after
          </summary>
          <div className="disc__body stack">
            <ul className="mv__mix">
              <MixLine title="Before" mix={r.mix.before} />
              <MixLine title="After" mix={r.mix.after} />
            </ul>
            <p className="meta">Shares of each group in this slot, counted from guests&rsquo; scans. A different mix does not mean the change caused it.</p>
          </div>
        </details>
      ) : null}
      {canWrite ? (
        <div className="row row--wrap">
          <button className="btn btn--sm" type="button" onClick={onEdit} disabled={busy}>
            Change
          </button>
          {confirming ? (
            <>
              <button className="btn btn--sm btn--primary" type="button" onClick={onRemove} disabled={busy}>
                Remove it
              </button>
              <button className="btn btn--sm btn--ghost" type="button" onClick={() => setConfirming(false)}>
                Keep it
              </button>
            </>
          ) : (
            <button className="btn btn--sm btn--ghost" type="button" onClick={() => setConfirming(true)} disabled={busy}>
              Remove
            </button>
          )}
        </div>
      ) : null}
    </article>
  );
}

export function MovesWorkspace({ base, canWrite }: { base: string; canWrite: boolean }) {
  const [doc, setDoc] = useState<MovesDoc | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  const [form, setForm] = useState<MoveForm | null>(null);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [tick, setTick] = useState(0);

  useEffect(() => {
    let live = true;
    api<MovesDoc>(`${base}/moves`)
      .then((d) => live && setDoc(d))
      .catch((e: unknown) => live && setProblem(e instanceof ApiError ? e.detail : "We couldn’t load your moves."));
    return () => {
      live = false;
    };
  }, [base, tick]);

  if (!doc && !problem) return <Loading />;
  if (!doc) return <Notice tone="error">{problem}</Notice>;

  const run = async (work: () => Promise<void>) => {
    setBusy(true);
    setProblem(null);
    try {
      await work();
      setTick((n) => n + 1);
    } catch (e) {
      setProblem(e instanceof ApiError ? e.detail : "That didn’t work. Please try again.");
    } finally {
      setBusy(false);
    }
  };

  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (!form) return;
    const made = moveBody(form);
    if ("problem" in made) {
      setProblem(made.problem);
      return;
    }
    void run(async () => {
      if (editingId) await api(`${base}/moves/${editingId}`, { method: "PUT", body: made.body });
      else await api(`${base}/moves`, { method: "POST", body: made.body });
      setForm(null);
      setEditingId(null);
    });
  };

  const ledger = doc.ledger;
  const totals = ledger.kinds.reduce((t, k) => ({ more: t.more + k.more, fewer: t.fewer + k.fewer, inconclusive: t.inconclusive + k.inconclusive, waiting: t.waiting + k.waiting }), { more: 0, fewer: 0, inconclusive: 0, waiting: 0 });

  return (
    <>
      <PageHead
        title="Moves"
        lead={`Log what you change, and see whether scans in the same slot moved in the ${doc.weeks} weeks around it. A few weeks of scans is a small sample, so the answer is often “inconclusive”, and it never says a change caused anything.`}
      >
        {canWrite && !form ? (
          <div>
            <button className="btn btn--primary" type="button" onClick={() => { setForm(emptyForm(doc.today)); setEditingId(null); setProblem(null); }} data-testid="new-move">
              <Icon name="plus" size="sm" />
              Log a move
            </button>
          </div>
        ) : null}
      </PageHead>
      {problem && !form ? <Notice tone="error">{problem}</Notice> : null}
      {form ? (
        <MoveFormCard
          form={form}
          setForm={(f) => {
            setForm(f);
            setProblem(null);
          }}
          busy={busy}
          onSubmit={submit}
          onCancel={() => { setForm(null); setEditingId(null); setProblem(null); }}
          editing={editingId !== null}
          problem={problem}
        />
      ) : null}

      {ledger.moves > 0 ? (
        <section className="card stack" aria-labelledby="mv-ledger-h" data-testid="ledger">
          <h2 className="card__title" id="mv-ledger-h">
            What your moves add up to
          </h2>
          <p>
            {ledger.moves} {ledger.moves === 1 ? "move" : "moves"}: {totals.more} with more scans, {totals.fewer} with fewer, {totals.inconclusive} inconclusive, {totals.waiting} too early to say.
          </p>
          <ul className="mv__kinds">
            {ledger.kinds.map((k) => (
              <li key={k.kind}>
                <strong>{KIND_LABELS[k.kind]}</strong> <span className="meta">{k.moves} {k.moves === 1 ? "move" : "moves"}: {k.more} more, {k.fewer} fewer, {k.inconclusive} inconclusive, {k.waiting} waiting</span>
              </li>
            ))}
          </ul>
          <p className="meta">One test is not enough to learn from, so nothing here changes how Nigiwai scores acts. The list is so you can see what has been tried.</p>
        </section>
      ) : null}

      {doc.moves.length === 0 && !form ? (
        <section className="card stack" data-testid="empty">
          <h2 className="card__title">No moves yet</h2>
          <p>
            When you book an act, change the menu or run an ad, log it here with the days and hours it was aimed at. After a couple of weeks Nigiwai counts scans in that same slot before and after, with its uncertainty. You can also accept an action on Today and log it from there.
          </p>
        </section>
      ) : null}

      <div className="stack" data-testid="moves">
        {doc.moves.map((m) => (
          <MoveCard
            key={m.id}
            move={m}
            canWrite={canWrite}
            busy={busy}
            onEdit={() => { setForm(formOf(m)); setEditingId(m.id); setProblem(null); window.scrollTo({ top: 0, behavior: "smooth" }); }}
            onRemove={() => void run(async () => { await api(`${base}/moves/${m.id}`, { method: "DELETE" }); })}
          />
        ))}
      </div>
      <p className="meta">Scans are guests who chose to answer, not a headcount. The same slot means the same days of the week and hours, counted per day it happened, only on days you are open.</p>
    </>
  );
}
