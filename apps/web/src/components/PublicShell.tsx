"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { Logo } from "@/components/Logo";
import { ThemeToggle } from "@/components/ThemeToggle";

const NAV = [
  { href: "/try", label: "Try it" },
  { href: "/evidence", label: "Evidence" },
  { href: "/privacy", label: "Privacy" },
  { href: "/business", label: "Business case" },
  { href: "/login", label: "Owner sign in" },
];

/** The frame for pages anyone can read: no account, no sidebar. */
export function PublicShell({ children }: { children: React.ReactNode }) {
  const path = usePathname();
  return (
    <div className="pubframe">
      <a className="skip-link" href="#main">
        Skip to the content
      </a>
      <header className="pubhead">
        <Logo />
        <nav className="pubnav" aria-label="Site">
          {NAV.map((n) => (
            <Link key={n.href} href={n.href} aria-current={path === n.href || path.startsWith(`${n.href}/`) ? "page" : undefined}>
              {n.label}
            </Link>
          ))}
          <ThemeToggle />
        </nav>
      </header>
      <main className="pubmain" id="main" tabIndex={-1}>
        {children}
      </main>
      <footer className="pubfoot">
        <p>Nigiwai reads a room&rsquo;s crowd from what its guests love. Taste data comes from Qloo; it describes the aggregate taste of groups and is never used to infer anything about a person.</p>
        <p>
          <Link href="/privacy">Privacy</Link> · <Link href="/evidence">Evidence</Link> · MIT licensed
        </p>
      </footer>
    </div>
  );
}
