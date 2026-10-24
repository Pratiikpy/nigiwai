"use client";

import Link from "next/link";
import { Icon } from "@/components/Icon";
import { Logo } from "@/components/Logo";

/** What a person sees if a page breaks while it draws. Nothing about the fault is shown; the reference lets us find it in the logs. */
export default function ErrorPage({ error, reset }: { error: Error & { digest?: string }; reset: () => void }) {
  return (
    <main className="auth" id="main">
      <div className="auth__card card" data-testid="page-error">
        <Logo />
        <div>
          <h1 className="display">Something went wrong on this page.</h1>
          <p className="muted" style={{ marginTop: "var(--s-2)" }}>
            It is on our side, not yours. Trying again often works; if it does not, go back to the front page.
          </p>
          {error.digest ? <p className="meta">Reference {error.digest}</p> : null}
        </div>
        <div className="row row--wrap">
          <button className="btn btn--primary" type="button" onClick={() => reset()}>
            <Icon name="refresh" />
            Try again
          </button>
          <Link className="btn" href="/">
            Go to the front page
          </Link>
        </div>
      </div>
    </main>
  );
}
