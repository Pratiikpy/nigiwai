"use client";

import { DAY_NAMES, type Hours } from "@/lib/onboarding";

/** Seven days of opening hours, Monday first; a closed day is `null`. Shared by Your venue and the onboarding interview. */
export function HoursEditor({ hours, onChange }: { hours: (Hours | null)[]; onChange: (next: (Hours | null)[]) => void }) {
  return (
    <fieldset className="qset" data-testid="hours">
      <legend>Opening hours</legend>
      <p className="field__hint">
        Used to find your quietest hours. Leave every day closed if you would rather not say. A closing time earlier than the opening time means after midnight.
      </p>
      <div className="hours-edit">
        {DAY_NAMES.map((day, i) => {
          const h = hours[i] ?? null;
          const set = (next: Hours | null) => onChange(hours.map((x, j) => (j === i ? next : x)));
          return (
            <div className="hours-edit__row" key={day}>
              <label className="check">
                <input type="checkbox" checked={h !== null} onChange={(e) => set(e.target.checked ? { open: "12:00", close: "23:00" } : null)} />
                <span>{day}</span>
              </label>
              {h ? (
                <>
                  <label className="sr-only" htmlFor={`o-${i}`}>
                    {day} opens
                  </label>
                  <input className="input" id={`o-${i}`} type="time" value={h.open} onChange={(e) => set({ ...h, open: e.target.value })} required />
                  <span aria-hidden="true">to</span>
                  <label className="sr-only" htmlFor={`c-${i}`}>
                    {day} closes
                  </label>
                  <input className="input" id={`c-${i}`} type="time" value={h.close} onChange={(e) => set({ ...h, close: e.target.value })} required />
                </>
              ) : (
                <span className="meta">Closed</span>
              )}
            </div>
          );
        })}
      </div>
      <div className="row row--wrap">
        <button
          className="btn btn--sm"
          type="button"
          onClick={() => {
            const first = hours.find(Boolean) ?? { open: "12:00", close: "23:00" };
            onChange(hours.map(() => first));
          }}
        >
          Copy the first open day to every day
        </button>
      </div>
    </fieldset>
  );
}
