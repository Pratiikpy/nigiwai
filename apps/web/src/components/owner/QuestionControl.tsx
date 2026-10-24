"use client";

import { type FormEvent, useState } from "react";
import { Icon } from "@/components/Icon";
import { HoursEditor } from "@/components/owner/HoursEditor";
import { Notice } from "@/components/owner/ui";
import { ApiError, api } from "@/lib/api";
import { DAY_NAMES, type Hours, type Place, type Question } from "@/lib/onboarding";

type Props = {
  q: Question;
  /** The answer already on record, when an answer is being changed. */
  initial?: unknown;
  busy: boolean;
  tenantPath: string;
  onAnswer: (value: unknown, place?: Place) => void;
  /** Present for a question that can be skipped. */
  onSkip?: () => void;
  /** Present when an answer is being changed rather than given. */
  onCancel?: () => void;
};

function Actions({ busy, label = "Continue", onSkip, onCancel, disabled }: Pick<Props, "busy" | "onSkip" | "onCancel"> & { label?: string; disabled?: boolean }) {
  return (
    <div className="row row--wrap">
      <button className="btn btn--primary" type="submit" disabled={busy || disabled}>
        {label}
      </button>
      {onSkip ? (
        <button className="btn" type="button" onClick={onSkip} disabled={busy} data-testid="skip">
          Skip this one
        </button>
      ) : null}
      {onCancel ? (
        <button className="btn btn--ghost" type="button" onClick={onCancel} disabled={busy}>
          Cancel
        </button>
      ) : null}
    </div>
  );
}

function Choice({ q, initial, busy, onAnswer, onCancel }: Props) {
  const [other, setOther] = useState("");
  return (
    <div className="stack">
      <div className="chips" role="group" aria-label={q.text}>
        {(q.choices ?? []).map((c) => (
          <button key={c.value} className="chipbtn" type="button" aria-pressed={initial === c.value} disabled={busy} onClick={() => onAnswer(c.value)}>
            {c.label}
          </button>
        ))}
      </div>
      {q.field === "currency" ? (
        <form
          className="row row--wrap"
          onSubmit={(e: FormEvent) => {
            e.preventDefault();
            if (other.trim()) onAnswer(other.trim().toUpperCase());
          }}
        >
          <label className="sr-only" htmlFor="q-other-currency">
            Another currency code
          </label>
          <input className="input onb-short" id="q-other-currency" maxLength={3} placeholder="Another, e.g. SEK" value={other} onChange={(e) => setOther(e.target.value.toUpperCase())} />
          <button className="btn" type="submit" disabled={busy || other.trim().length !== 3}>
            Use this code
          </button>
        </form>
      ) : null}
      {onCancel ? (
        <div>
          <button className="btn btn--ghost" type="button" onClick={onCancel} disabled={busy}>
            Cancel
          </button>
        </div>
      ) : null}
    </div>
  );
}

function Multi({ q, initial, busy, onAnswer, onCancel }: Props) {
  const [picked, setPicked] = useState<string[]>(Array.isArray(initial) ? (initial as string[]) : []);
  const max = q.max ?? 3;
  return (
    <form
      className="stack"
      onSubmit={(e) => {
        e.preventDefault();
        if (picked.length) onAnswer(picked);
      }}
    >
      <div className="chips" role="group" aria-label={q.text}>
        {(q.choices ?? []).map((c) => {
          const on = picked.includes(c.value);
          return (
            <button
              key={c.value}
              className="chipbtn"
              type="button"
              aria-pressed={on}
              disabled={busy || (!on && picked.length >= max)}
              onClick={() => setPicked((p) => (on ? p.filter((x) => x !== c.value) : [...p, c.value]))}
            >
              {c.label}
            </button>
          );
        })}
      </div>
      <p className="field__hint">{picked.length ? `${picked.length} of ${max} chosen.` : `Choose up to ${max}.`}</p>
      <Actions busy={busy} disabled={!picked.length} onCancel={onCancel} />
    </form>
  );
}

function Area({ q, initial, busy, tenantPath, onAnswer, onCancel }: Props) {
  const [text, setText] = useState(typeof initial === "string" ? initial : "");
  const [results, setResults] = useState<Place[] | null>(null);
  const [searching, setSearching] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  const typed = text.replace(/\s+/g, " ").trim();

  const find = async (e: FormEvent) => {
    e.preventDefault();
    if (typed.length < 3 || searching) return;
    setSearching(true);
    setProblem(null);
    try {
      const found = await api<{ places: Place[] }>(`${tenantPath}/places/search?q=${encodeURIComponent(typed)}`);
      setResults(found.places);
    } catch (error) {
      setResults(null);
      setProblem(error instanceof ApiError ? error.detail : "We couldn’t search just now. You can use the address without a position.");
    } finally {
      setSearching(false);
    }
  };

  return (
    <div className="stack">
      <form className="stack" onSubmit={find}>
        <div className="field">
          <label htmlFor="q-area">Address</label>
          <input
            className="input"
            id="q-area"
            maxLength={300}
            autoComplete="street-address"
            placeholder="12 Quill Street, Manchester"
            value={text}
            onChange={(e) => {
              setText(e.target.value);
              setResults(null);
            }}
          />
          <p className="field__hint">Pressing “Find it on the map” sends only what you typed to OpenStreetMap’s search, to find the position.</p>
        </div>
        <div className="row row--wrap">
          <button className="btn btn--primary" type="submit" disabled={busy || searching || typed.length < 3} data-testid="find-place">
            <Icon name="search" size="sm" />
            {searching ? "Searching…" : "Find it on the map"}
          </button>
          <button className="btn" type="button" disabled={busy || typed.length < 3} onClick={() => onAnswer(typed)} data-testid="use-typed">
            Use it without a map position
          </button>
          {onCancel ? (
            <button className="btn btn--ghost" type="button" onClick={onCancel} disabled={busy}>
              Cancel
            </button>
          ) : null}
        </div>
      </form>
      {problem ? <Notice tone="warn">{problem}</Notice> : null}
      {results && results.length === 0 ? <Notice tone="warn">Nothing matched that. Add the town, or use the address without a map position.</Notice> : null}
      {results && results.length ? (
        <fieldset className="qset">
          <legend>Is it one of these?</legend>
          <ul className="onb-places" data-testid="places">
            {results.map((p) => (
              <li key={`${p.lat},${p.lon},${p.label}`}>
                <button className="onb-place" type="button" disabled={busy} onClick={() => onAnswer(p.label, p)}>
                  <Icon name="pin" />
                  <span>{p.label}</span>
                </button>
              </li>
            ))}
          </ul>
          <p className="meta">Map data © OpenStreetMap contributors.</p>
        </fieldset>
      ) : null}
      <span className="sr-only">{q.text}</span>
    </div>
  );
}

function HoursAnswer({ initial, busy, onAnswer, onSkip, onCancel }: Props) {
  const [hours, setHours] = useState<(Hours | null)[]>(Array.isArray(initial) && initial.length === 7 ? (initial as (Hours | null)[]) : Array(7).fill(null));
  const open = hours.some(Boolean);
  return (
    <form
      className="stack"
      onSubmit={(e) => {
        e.preventDefault();
        if (open) onAnswer(hours);
      }}
    >
      <HoursEditor hours={hours} onChange={setHours} />
      {!open ? <p className="field__hint">Tick at least one day you are open, or skip this for now.</p> : null}
      <Actions busy={busy} disabled={!open} label="Save the hours" onSkip={onSkip} onCancel={onCancel} />
    </form>
  );
}

function NumberAnswer({ q, initial, busy, onAnswer, onSkip, onCancel }: Props) {
  const [value, setValue] = useState(typeof initial === "number" ? String(initial) : "");
  return (
    <form
      className="stack"
      onSubmit={(e) => {
        e.preventDefault();
        if (value.trim()) onAnswer(Number(value));
      }}
    >
      <div className="field">
        <label htmlFor="q-number">People</label>
        <input className="input onb-short" id="q-number" type="number" inputMode="numeric" min={1} max={200000} value={value} onChange={(e) => setValue(e.target.value)} aria-describedby="q-number-h" />
        <p className="field__hint" id="q-number-h">
          {q.why}
        </p>
      </div>
      <Actions busy={busy} disabled={!value.trim()} onSkip={onSkip} onCancel={onCancel} />
    </form>
  );
}

function Days({ initial, busy, onAnswer, onSkip, onCancel }: Props) {
  const [days, setDays] = useState<number[]>(Array.isArray(initial) ? (initial as number[]) : []);
  return (
    <form
      className="stack"
      onSubmit={(e) => {
        e.preventDefault();
        onAnswer(days);
      }}
    >
      <div className="chips" role="group" aria-label="Nights with live music">
        {DAY_NAMES.map((name, i) => (
          <button key={name} className="chipbtn" type="button" aria-pressed={days.includes(i)} disabled={busy} onClick={() => setDays((d) => (d.includes(i) ? d.filter((x) => x !== i) : [...d, i].sort()))}>
            {name}
          </button>
        ))}
      </div>
      <Actions busy={busy} label={days.length ? "Continue" : "No regular nights"} onSkip={onSkip} onCancel={onCancel} />
    </form>
  );
}

function List({ initial, busy, onAnswer, onSkip, onCancel }: Props) {
  const [text, setText] = useState(Array.isArray(initial) ? (initial as string[]).join(", ") : "");
  return (
    <form
      className="stack"
      onSubmit={(e) => {
        e.preventDefault();
        onAnswer(text);
      }}
    >
      <div className="field">
        <label htmlFor="q-list">Genres</label>
        <input className="input" id="q-list" maxLength={600} placeholder="metal, drill" value={text} onChange={(e) => setText(e.target.value)} />
        <p className="field__hint">Separate with commas. Leave it empty if there are none.</p>
      </div>
      <Actions busy={busy} label={text.trim() ? "Continue" : "None"} onSkip={onSkip} onCancel={onCancel} />
    </form>
  );
}

function YesNo({ q, initial, busy, onAnswer, onCancel }: Props) {
  return (
    <div className="stack">
      <div className="chips" role="group" aria-label={q.text}>
        <button className="chipbtn" type="button" aria-pressed={initial === true} disabled={busy} onClick={() => onAnswer(true)}>
          Yes
        </button>
        <button className="chipbtn" type="button" aria-pressed={initial === false} disabled={busy} onClick={() => onAnswer(false)}>
          No
        </button>
      </div>
      {onCancel ? (
        <div>
          <button className="btn btn--ghost" type="button" onClick={onCancel} disabled={busy}>
            Cancel
          </button>
        </div>
      ) : null}
    </div>
  );
}

/** The right control for one checklist question. Each one answers through the same `onAnswer`, so the page treats a chip, a
 * weekly timetable and a typed address alike; the server checks every value again. */
export function QuestionControl(props: Props) {
  switch (props.q.kind) {
    case "choice":
      return <Choice {...props} />;
    case "multi":
      return <Multi {...props} />;
    case "text":
      return <Area {...props} />;
    case "hours":
      return <HoursAnswer {...props} />;
    case "number":
      return <NumberAnswer {...props} />;
    case "days":
      return <Days {...props} />;
    case "list":
      return <List {...props} />;
    case "yesno":
      return <YesNo {...props} />;
    default:
      return null;
  }
}
