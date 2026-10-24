"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { Icon } from "@/components/Icon";
import { Logo } from "@/components/Logo";
import { RecoveryCode } from "@/components/auth/RecoveryCode";
import { ApiError, api } from "@/lib/api";

/** A forgotten password, set again with the recovery code made at sign-up. Success shows the next code, because each one works once. */
export function ForgotForm() {
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [code, setCode] = useState("");
  const [password, setPassword] = useState("");
  const [show, setShow] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [fresh, setFresh] = useState<string | null>(null);

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    if (busy) return;
    setBusy(true);
    setError(null);
    try {
      const done = await api<{ recovery_code: string }>("/auth/recover", { method: "POST", body: { email, recovery_code: code, new_password: password } });
      setFresh(done.recovery_code);
    } catch (e) {
      setError(e instanceof ApiError ? e.detail : "Something went wrong. Please try again.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <main className="auth" id="main">
      <div className="auth__card card">
        <Logo />
        {fresh ? (
          <RecoveryCode code={fresh} email={email} heading="Your password is changed" doneLabel="Go to sign in" onDone={() => router.replace("/login")} />
        ) : (
          <>
            <div>
              <h1 className="display">Forgot your password?</h1>
              <p className="muted" style={{ marginTop: "var(--s-2)" }}>
                Enter your email and the recovery code you were shown when you signed up. You will choose a new password, and every device is signed out.
              </p>
            </div>
            <form onSubmit={submit} noValidate>
              <div className="field">
                <label htmlFor="email">Email</label>
                <input className="input" id="email" name="email" type="email" autoComplete="email" inputMode="email" required value={email} onChange={(e) => setEmail(e.target.value)} />
              </div>
              <div className="field">
                <label htmlFor="code">Recovery code</label>
                <input
                  className="input rc-input"
                  id="code"
                  name="code"
                  autoComplete="off"
                  autoCapitalize="characters"
                  spellCheck={false}
                  required
                  maxLength={100}
                  value={code}
                  onChange={(e) => setCode(e.target.value)}
                  aria-describedby="code-hint"
                />
                <p className="field__hint" id="code-hint">
                  Four groups of five letters and numbers. Capitals and dashes do not matter.
                </p>
              </div>
              <div className="field">
                <label htmlFor="password">New password</label>
                <input
                  className="input"
                  id="password"
                  name="password"
                  type={show ? "text" : "password"}
                  autoComplete="new-password"
                  required
                  maxLength={200}
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  aria-describedby="password-hint"
                />
                <p className="field__hint" id="password-hint">
                  At least 10 characters.{" "}
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
              <button className="btn btn--primary btn--lg" type="submit" data-testid="forgot-submit" disabled={busy}>
                {busy ? "One moment…" : "Set a new password"}
              </button>
            </form>
            <p className="auth__alt">
              Lost the code too? There is no other way back in to an account, so you would need to <Link href="/signup">start a new one</Link>.{" "}
              <Link href="/login">Back to sign in</Link>
            </p>
          </>
        )}
      </div>
    </main>
  );
}
