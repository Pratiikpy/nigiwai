import type { Metadata } from "next";
import Link from "next/link";
import { Logo } from "@/components/Logo";

export const metadata: Metadata = { title: "Page not found", robots: { index: false, follow: false } };

/** Any address that matches nothing: said plainly, with the ways back. */
export default function NotFound() {
  return (
    <main className="auth" id="main">
      <div className="auth__card card" data-testid="not-found">
        <Logo />
        <div>
          <p className="eyebrow">404</p>
          <h1 className="display">We can&rsquo;t find that page.</h1>
          <p className="muted" style={{ marginTop: "var(--s-2)" }}>
            The address may have a typo, or the page may have been taken down. A poster or an invitation link that stopped working is best checked with whoever gave it to you.
          </p>
        </div>
        <div className="row row--wrap">
          <Link className="btn btn--primary" href="/">
            Go to the front page
          </Link>
          <Link className="btn" href="/login">
            Sign in
          </Link>
        </div>
      </div>
    </main>
  );
}
