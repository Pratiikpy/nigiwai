"use client";

import { useEffect, useState } from "react";
import { Notice } from "@/components/owner/ui";
import { ApiError, api } from "@/lib/api";

type Consent = { version: string; body: string };

/** The owner waitlist: an email and a plain consent line. The hidden field catches scripts, and nothing says whether an address was already on the list. */
export function Waitlist() {
  const [consent, setConsent] = useState<Consent | null>(null);
  const [email, setEmail] = useState("");
  const [agreed, setAgreed] = useState(false);
  const [trap, setTrap] = useState("");
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);

  useEffect(() => {
    let live = true;
    api<Consent>("/public/waitlist/consent")
      .then((c) => live && setConsent(c))
      .catch(() => live && setProblem("We couldn’t load the sign-up note. Please try again later."));
    return () => {
      live = false;
    };
  }, []);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (busy) return;
    setBusy(true);
    setProblem(null);
    try {
      await api("/public/waitlist", { method: "POST", body: { email: email.trim(), consent: agreed, website: trap } });
      setDone(true);
    } catch (err) {
      setProblem(err instanceof ApiError ? err.detail : "That didn’t work. Please try again.");
    } finally {
      setBusy(false);
    }
  };

  if (done) {
    return (
      <Notice tone="ok">
        <strong>You’re on the list.</strong> We’ll write once, when pricing and launch are settled.
      </Notice>
    );
  }
  return (
    <form className="waitlist" onSubmit={submit} noValidate>
      <div className="field">
        <label htmlFor="wl-email">Work email</label>
        <input
          className="input"
          id="wl-email"
          type="email"
          autoComplete="email"
          placeholder="you@yourvenue.example"
          value={email}
          maxLength={254}
          onChange={(e) => setEmail(e.target.value)}
          required
        />
      </div>
      {/* Not for people: scripts that fill every field fill this one. */}
      <div aria-hidden="true" style={{ position: "absolute", left: "-10000px", height: 0, overflow: "hidden" }}>
        <label htmlFor="wl-website">Website</label>
        <input id="wl-website" tabIndex={-1} autoComplete="off" value={trap} onChange={(e) => setTrap(e.target.value)} />
      </div>
      <label className="chk">
        <input type="checkbox" checked={agreed} onChange={(e) => setAgreed(e.target.checked)} />
        <span className="consent">{consent?.body ?? "…"}</span>
      </label>
      {problem ? <Notice tone="error">{problem}</Notice> : null}
      <button className="btn btn--primary" type="submit" disabled={busy || !consent}>
        {busy ? "Adding…" : "Join the waitlist"}
      </button>
    </form>
  );
}
