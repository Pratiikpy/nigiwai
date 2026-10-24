"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { Icon } from "@/components/Icon";
import { Logo } from "@/components/Logo";
import { RecoveryCode } from "@/components/auth/RecoveryCode";
import { ApiError, api, setCsrf, type Me } from "@/lib/api";
import { rememberAccount } from "@/lib/session";
import { type Peek, ROLE_CAN, ROLE_NAME, tokenFromHash } from "@/lib/team";

type Load =
  | { status: "loading" }
  | { status: "none" } // no secret in the address
  | { status: "unknown" } // the secret matches no invitation
  | { status: "failed"; message: string }
  | { status: "ready"; peek: Peek; me: Me | null };

/** The page an invitation link opens. It says what the link is for, then either joins the signed-in person or makes them an account. */
export function InviteJoin() {
  const router = useRouter();
  const token = useRef<string | null>(null);
  const [load, setLoad] = useState<Load>({ status: "loading" });
  const [mode, setMode] = useState<"create" | "signin">("create");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [show, setShow] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [recovery, setRecovery] = useState<string | null>(null);

  // Pasting a different link into the address bar of this tab changes only the part after the #, so the page is not reloaded:
  // listen for that and open the new invitation.
  const [opened, setOpened] = useState(0);
  useEffect(() => {
    const again = () => setOpened((n) => n + 1);
    window.addEventListener("hashchange", again);
    return () => window.removeEventListener("hashchange", again);
  }, []);

  useEffect(() => {
    let live = true;
    (async () => {
      const secret = tokenFromHash(window.location.hash);
      token.current = secret;
      setError(null);
      setLoad({ status: "loading" });
      if (!secret) {
        if (live) setLoad({ status: "none" });
        return;
      }
      try {
        const peek = await api<Peek>("/invitations/peek", { method: "POST", body: { token: secret } });
        let me: Me | null = null;
        try {
          me = await api<Me>("/auth/me");
          setCsrf(me.csrf_token);
        } catch {
          /* not signed in: the form is shown */
        }
        if (live) setLoad({ status: "ready", peek, me });
      } catch (e) {
        if (!live) return;
        if (e instanceof ApiError && (e.status === 404 || e.status === 422)) setLoad({ status: "unknown" });
        else setLoad({ status: "failed", message: e instanceof ApiError ? e.detail : "Something went wrong. Please try again." });
      }
    })();
    return () => {
      live = false;
    };
  }, [opened]);

  const finish = (tenantId: string) => {
    rememberAccount(tenantId);
    router.replace("/app");
  };

  const accept = async () => {
    const joined = await api<{ tenant_id: string }>("/invitations/accept", { method: "POST", body: { token: token.current } });
    finish(joined.tenant_id);
  };

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    if (busy || !token.current) return;
    setBusy(true);
    setError(null);
    try {
      if (mode === "create") {
        const me = await api<Me>("/auth/signup", { method: "POST", body: { email, password, invite_token: token.current } });
        setCsrf(me.csrf_token);
        const first = me.tenants[0];
        if (first) rememberAccount(first.id);
        if (me.recovery_code) {
          setRecovery(me.recovery_code); // shown once, before going on
          setBusy(false);
          return;
        }
        router.replace("/app");
        return;
      }
      const me = await api<Me>("/auth/login", { method: "POST", body: { email, password } });
      setCsrf(me.csrf_token);
      await accept();
    } catch (e) {
      setError(e instanceof ApiError ? e.detail : "Something went wrong. Please try again.");
      setBusy(false);
    }
  };

  const joinAsMe = async () => {
    if (busy) return;
    setBusy(true);
    setError(null);
    try {
      await accept();
    } catch (e) {
      setError(e instanceof ApiError ? e.detail : "Something went wrong. Please try again.");
      setBusy(false);
    }
  };

  const switchPerson = async () => {
    try {
      await api<void>("/auth/logout", { method: "POST" });
    } catch {
      /* already signed out */
    }
    setCsrf(null);
    setLoad((l) => (l.status === "ready" ? { ...l, me: null } : l));
  };

  const dead = (title: string, body: string) => (
    <main className="auth" id="main">
      <div className="auth__card card" data-testid="invite-dead">
        <Logo />
        <h1 className="display">{title}</h1>
        <p className="muted">{body}</p>
        <Link className="btn" href="/login">
          Go to sign in
        </Link>
      </div>
    </main>
  );

  if (load.status === "loading") {
    return (
      <main className="auth" id="main">
        <div className="res-status" role="status">
          <span className="spin" aria-hidden="true" />
          Opening your invitation…
        </div>
      </main>
    );
  }
  if (load.status === "none") return dead("This link is incomplete.", "An invitation link ends with a long code. Copy the whole link again from the message it came in.");
  if (load.status === "unknown") return dead("This invitation link is not valid.", "Check that the whole link was copied. If it was, ask the owner for a new one.");
  if (load.status === "failed") return dead("We couldn’t open this invitation.", load.message);
  const { peek, me } = load;
  if (recovery)
    return (
      <main className="auth" id="main">
        <div className="auth__card card">
          <Logo />
          <RecoveryCode code={recovery} email={email} heading="You have joined" onDone={() => router.replace("/app")} />
        </div>
      </main>
    );
  if (peek.state !== "open") return dead(peek.state === "used" ? "This invitation was already used." : peek.state === "revoked" ? "This invitation was withdrawn." : "This invitation has expired.", peek.reason ?? "Ask the owner for a new one.");

  return (
    <main className="auth" id="main">
      <div className="auth__card card" data-testid="invite-open">
        <Logo />
        <div>
          <p className="eyebrow">You are invited</p>
          <h1 className="display" data-testid="invite-account">
            Join {peek.account}
          </h1>
          <p className="muted" style={{ marginTop: "var(--s-2)" }}>
            As a {ROLE_NAME[peek.role].toLowerCase()}. {ROLE_CAN[peek.role]}
          </p>
        </div>

        {error ? (
          <div className="banner" data-tone="error" role="alert">
            <Icon name="alert" />
            <div className="banner__body">{error}</div>
          </div>
        ) : null}

        {me ? (
          <div className="stack">
            <p>
              You are signed in as <strong>{me.email}</strong>.
            </p>
            <button className="btn btn--primary btn--lg" type="button" data-testid="invite-join" disabled={busy} onClick={() => void joinAsMe()}>
              {busy ? "One moment…" : `Join ${peek.account}`}
            </button>
            <p className="auth__alt">
              Not you?{" "}
              <button type="button" className="linklike" onClick={() => void switchPerson()}>
                Use a different account
              </button>
            </p>
          </div>
        ) : (
          <form onSubmit={submit} noValidate>
            <div className="field">
              <label htmlFor="email">Email</label>
              <input className="input" id="email" name="email" type="email" autoComplete="email" inputMode="email" required value={email} onChange={(e) => setEmail(e.target.value)} />
            </div>
            <div className="field">
              <label htmlFor="password">{mode === "create" ? "Choose a password" : "Password"}</label>
              <input
                className="input"
                id="password"
                name="password"
                type={show ? "text" : "password"}
                autoComplete={mode === "create" ? "new-password" : "current-password"}
                required
                maxLength={200}
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                aria-describedby="password-hint"
              />
              <p className="field__hint" id="password-hint">
                {mode === "create" ? "At least 10 characters. A few random words is stronger than a clever one. " : null}
                <button type="button" className="linklike" onClick={() => setShow((v) => !v)} aria-pressed={show}>
                  {show ? "Hide password" : "Show password"}
                </button>
              </p>
            </div>
            <button className="btn btn--primary btn--lg" type="submit" data-testid="invite-submit" disabled={busy}>
              {busy ? "One moment…" : mode === "create" ? `Create my account and join` : `Sign in and join`}
            </button>
            <p className="auth__alt">
              {mode === "create" ? (
                <>
                  Already have an account?{" "}
                  <button type="button" className="linklike" data-testid="invite-have-account" onClick={() => { setMode("signin"); setError(null); }}>
                    Sign in instead
                  </button>
                </>
              ) : (
                <>
                  New here?{" "}
                  <button type="button" className="linklike" onClick={() => { setMode("create"); setError(null); }}>
                    Create an account
                  </button>
                </>
              )}
            </p>
          </form>
        )}
      </div>
    </main>
  );
}
