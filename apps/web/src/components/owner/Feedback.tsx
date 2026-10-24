"use client";

import { useState } from "react";
import { ApiError, api } from "@/lib/api";
import { useVenue } from "@/lib/venue";

/** "Was this useful?" on a Soundcheck or a brief. What is sent is a yes or no and a short line: nothing that says who sent it. */
export function Feedback({ kind }: { kind: "soundcheck" | "brief" }) {
  const { tenantPath } = useVenue();
  const [answer, setAnswer] = useState<boolean | null>(null);
  const [note, setNote] = useState("");
  const [state, setState] = useState<"idle" | "sent" | "failed">("idle");
  const [problem, setProblem] = useState<string | null>(null);

  const send = async () => {
    if (answer === null) return;
    try {
      await api(`${tenantPath}/feedback`, { method: "POST", body: { kind, useful: answer, note: note.trim() } });
      setState("sent");
    } catch (e) {
      setProblem(e instanceof ApiError ? e.detail : "We couldn’t send that.");
      setState("failed");
    }
  };

  if (state === "sent") {
    return (
      <p className="meta noprint" role="status" data-testid="feedback-thanks">
        Thank you. It was sent without your name or your venue.
      </p>
    );
  }
  return (
    <div className="stack stack--sm noprint" role="group" aria-label="Was this useful?" data-testid="feedback">
      <div className="row row--wrap">
        <span className="meta">Was this useful?</span>
        <button className="btn btn--sm" type="button" aria-pressed={answer === true} onClick={() => setAnswer(true)}>
          Yes
        </button>
        <button className="btn btn--sm" type="button" aria-pressed={answer === false} onClick={() => setAnswer(false)}>
          No
        </button>
        <span className="meta">Sent without any identity.</span>
      </div>
      {answer !== null ? (
        <div className="row row--wrap">
          <label className="sr-only" htmlFor={`fb-${kind}`}>
            Anything to add? (optional)
          </label>
          <input
            id={`fb-${kind}`}
            className="input grow"
            maxLength={280}
            placeholder="Anything to add? (optional, one line)"
            value={note}
            onChange={(e) => setNote(e.target.value)}
          />
          <button className="btn btn--sm btn--primary" type="button" onClick={() => void send()}>
            Send
          </button>
        </div>
      ) : null}
      {problem ? <p className="meta">{problem}</p> : null}
    </div>
  );
}
