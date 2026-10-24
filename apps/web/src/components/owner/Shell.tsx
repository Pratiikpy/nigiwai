"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useState } from "react";
import { Icon, type IconName } from "@/components/Icon";
import { Logo } from "@/components/Logo";
import { ThemeToggle } from "@/components/ThemeToggle";
import { useSession } from "@/lib/session";
import { MODULE_OF_PATH } from "@/lib/onboarding";
import { VenueProvider, useVenue } from "@/lib/venue";

const NAV: { href: string; label: string; icon: IconName }[] = [
  { href: "/app", label: "Overview", icon: "layers" },
  { href: "/app/onboarding", label: "Your plan", icon: "sliders" },
  { href: "/app/today", label: "Today", icon: "calendar" },
  { href: "/app/venue", label: "Your venue", icon: "pin" },
  { href: "/app/survey", label: "Survey", icon: "list" },
  { href: "/app/map", label: "Crowd map", icon: "map" },
  { href: "/app/people", label: "My people", icon: "people" },
  { href: "/app/soundcheck", label: "Soundcheck", icon: "bolt" },
  { href: "/app/sound", label: "Sound plan", icon: "music" },
  { href: "/app/grow", label: "Grow", icon: "hex" },
  { href: "/app/atlas", label: "Atlas", icon: "compare" },
  { href: "/app/moves", label: "Moves", icon: "flag" },
  { href: "/app/drafts", label: "Drafts", icon: "send" },
  { href: "/app/ask", label: "Ask Nigiwai", icon: "chat" },
  { href: "/app/brief", label: "Booking Brief", icon: "download" },
  { href: "/app/proof", label: "Proof", icon: "shield" },
  { href: "/app/posters", label: "QR posters", icon: "qr" },
];

/** The side menu. Once the owner has a plan, the tools it leaves off are hidden here (their pages still open by address). */
function Nav({ path, onNavigate }: { path: string; onNavigate: () => void }) {
  const { venue } = useVenue();
  const off = new Set((venue?.plan?.modules ?? []).filter((m) => !m.on).map((m) => m.id));
  return (
    <nav className="nav" aria-label="Pages">
      {NAV.filter((item) => !off.has(MODULE_OF_PATH[item.href] ?? "")).map((item) => (
        <Link
          key={item.href}
          href={item.href}
          aria-current={(path === item.href || (item.href !== "/app" && path.startsWith(`${item.href}/`))) ? "page" : undefined}
          onClick={onNavigate}
        >
          <Icon name={item.icon} />
          {item.label}
        </Link>
      ))}
    </nav>
  );
}

export function Shell({ children }: { children: React.ReactNode }) {
  const { state, signOut } = useSession();
  const path = usePathname();
  const [open, setOpen] = useState(false);

  if (state.status === "loading") {
    return (
      <div className="auth">
        <div className="res-status" role="status">
          <span className="spin" aria-hidden="true" />
          Loading your venue…
        </div>
      </div>
    );
  }
  if (state.status === "error") {
    return (
      <div className="auth">
        <div className="auth__card card">
          <h1 className="display">We couldn&rsquo;t load your account.</h1>
          <p className="muted">{state.message}</p>
          <button className="btn btn--primary" type="button" onClick={() => location.reload()}>
            <Icon name="refresh" /> Try again
          </button>
        </div>
      </div>
    );
  }

  return (
    <VenueProvider>
    <div className="shell">
      <a className="skip-link" href="#main">
        Skip to the page
      </a>
      <header className="shell__top">
        <Logo href="/app" />
        <button className="btn btn--sm" type="button" onClick={() => setOpen((v) => !v)} aria-expanded={open} aria-controls="side">
          <Icon name={open ? "x" : "menu"} size="sm" />
          Menu
        </button>
      </header>
      {open ? <div className="shell__scrim" onClick={() => setOpen(false)} aria-hidden="true" /> : null}
      <aside className={`shell__side${open ? " is-open" : ""}`} id="side" aria-label="Main">
        <Logo href="/app" />
        <div className="side__who">
          <strong>{state.tenant.name}</strong>
          <span className="meta">{state.me.email}</span>
        </div>
        <Nav path={path} onNavigate={() => setOpen(false)} />
        <div className="side__foot">
          <ThemeToggle />
          <button className="btn btn--sm btn--ghost" type="button" onClick={() => void signOut()}>
            Sign out
          </button>
        </div>
      </aside>
      <main className="shell__main" id="main" tabIndex={-1}>
        {children}
      </main>
    </div>
    </VenueProvider>
  );
}
