"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { Icon } from "@/components/Icon";
import { Logo } from "@/components/Logo";
import { RecoveryCode } from "@/components/auth/RecoveryCode";
import { ApiError, api, setCsrf, type Me } from "@/lib/api";

type Mode = "login" | "signup";

/** Where to go after signing in: back to the page the person was on when their session ended, if it is one of our own owner pages. */
function whereNext(): string {
  const next = new URLSearchParams(window.location.search).get("next");
  return next && /^\/app(\/[A-Za-z0-9_\-./?=&%]*)?$/.test(next) && !next.includes("//") && !next.includes("..") ? next : "/app";
}

/** One form for both sign-in and sign-up. The server's wording is shown as it comes: it never says which half was wrong. */
export function AuthForm({ mode }: { mode: Mode }) {
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [business, setBusiness] = useState("");
  const [show, setShow] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [recovery, setRecovery] = useState<string | null>(null);
  const signup = mode === "signup";

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    if (busy) return;
    setBusy(true);
    setError(null);
    try {
      const me = await api<Me>(signup ? "/auth/signup" : "/auth/login", {
        method: "POST",
        body: signup ? { email, password, business_name: business } : { email, password },
      });
      setCsrf(me.csrf_token);
      if (me.recovery_code) {
        setRecovery(me.recovery_code); // shown once, before going on
        setBusy(false);
        return;
      }
      router.replace(whereNext());
    } catch (e) {
      setError(e instanceof ApiError ? e.detail : "Something went wrong. Please try again.");
      setBusy(false);
    }
  };

  return (
    <main className="auth" id="main">
      <div className="auth__card card">
        <Logo />
        {recovery ? (
          <RecoveryCode code={recovery} email={email} heading="Your account is ready" onDone={() => router.replace(whereNext())} />
        ) : (
          <>
        <div>
          <h1 className="display">{signup ? "Create your account" : "Welcome back"}</h1>
          <p className="muted" style={{ marginTop: "var(--s-2)" }}>
            {signup ? "Set up your venue and put a QR poster on the counter." : "Sign in to see what your crowd loves."}
          </p>
        </div>
        <form onSubmit={submit} noValidate>
          {signup ? (
            <div className="field">
              <label htmlFor="business">Venue or business name</label>
              <input
                className="input"
                id="business"
                name="business"
                autoComplete="organization"
                required
                maxLength={120}
                value={business}
                onChange={(e) => setBusiness(e.target.value)}
              />
            </div>
          ) : null}
          <div className="field">
            <label htmlFor="email">Email</label>
            <input
              className="input"
              id="email"
              name="email"
              type="email"
              autoComplete="email"
              inputMode="email"
              required
              value={email}
              onChange={(e) => setEmail(e.target.value)}
            />
          </div>
          <div className="field">
            <label htmlFor="password">Password</label>
            <div className="search">
              <input
                className="input"
                id="password"
                name="password"
                type={show ? "text" : "password"}
                autoComplete={signup ? "new-password" : "current-password"}
                required
                maxLength={200}
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                aria-describedby="password-hint"
              />
            </div>
            <p className="field__hint" id="password-hint">
              {signup ? "At least 10 characters. A few random words is stronger than a clever one. " : null}
              <button type="button" className="linklike" onClick={() => setShow((v) => !v)} aria-pressed={show}>
                {show ? "Hide password" : "Show password"}
              </button>
            </p>
          </div>
          {error ? (
            <div className="banner" data-tone="error" role="alert">
              <Icon name="alert" />
              <div className="banner__body">{error}</div>
            </div>
          ) : null}
          <button className="btn btn--primary btn--lg" type="submit" disabled={busy}>
            {busy ? "One moment…" : signup ? "Create account" : "Sign in"}
          </button>
        </form>
        {signup ? null : (
          <p className="auth__alt">
            <Link href="/forgot" data-testid="forgot-link">
              Forgot your password?
            </Link>
          </p>
        )}
        <p className="auth__alt">
          {signup ? (
            <>
              Already have an account? <Link href="/login">Sign in</Link>
            </>
          ) : (
            <>
              New here? <Link href="/signup">Create an account</Link>
            </>
          )}
        </p>
          </>
        )}
      </div>
    </main>
  );
}
