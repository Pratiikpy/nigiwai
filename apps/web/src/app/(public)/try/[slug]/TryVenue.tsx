"use client";

import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { type KeyboardEvent, useEffect, useRef, useState } from "react";
import { Label } from "@/components/Label";
import { BriefWorkspace } from "@/components/owner/BriefWorkspace";
import { MapWorkspace } from "@/components/owner/MapWorkspace";
import { SoundcheckWorkspace } from "@/components/owner/SoundcheckWorkspace";
import { Loading } from "@/components/owner/ui";
import { ApiError, api } from "@/lib/api";
import { type DemoVenue, demoBase, matched, refreshedOn, years } from "@/lib/demo";

const VIEWS = [
  { id: "soundcheck", label: "Soundcheck" },
  { id: "map", label: "Crowd map" },
  { id: "brief", label: "Booking Brief" },
] as const;
type View = (typeof VIEWS)[number]["id"];

function parseView(raw: string | null): View {
  return VIEWS.find((v) => v.id === raw)?.id ?? "soundcheck";
}

/** One demo venue: the same three workspaces an owner has, pointed at the venue's public routes. */
export function TryVenue({ slug }: { slug: string }) {
  const router = useRouter();
  const path = usePathname();
  const params = useSearchParams();
  const view = parseView(params.get("tab"));
  const [venue, setVenue] = useState<DemoVenue | null>(null);
  const [problem, setProblem] = useState<{ status: number; detail: string } | null>(null);
  const tabs = useRef<Array<HTMLButtonElement | null>>([]);
  const base = demoBase(slug);

  useEffect(() => {
    let live = true;
    api<DemoVenue>(base)
      .then((v) => live && setVenue(v))
      .catch((e: unknown) => {
        if (!live) return;
        setProblem(
          e instanceof ApiError
            ? { status: e.status, detail: e.message }
            : { status: 0, detail: "The demo could not be reached. Please reload the page in a moment." },
        );
      });
    return () => {
      live = false;
    };
  }, [base]);

  function go(next: View) {
    const q = new URLSearchParams(params.toString());
    // What a view keeps in the address belongs to that view only.
    for (const key of ["sc", "period", "layers", "sel", "view"]) q.delete(key);
    if (next === "soundcheck") q.delete("tab");
    else q.set("tab", next);
    const qs = q.toString();
    router.replace(qs ? `${path}?${qs}` : path, { scroll: false });
  }

  function onKey(e: KeyboardEvent<HTMLButtonElement>, i: number) {
    const last = VIEWS.length - 1;
    const to = e.key === "ArrowRight" ? (i === last ? 0 : i + 1) : e.key === "ArrowLeft" ? (i === 0 ? last : i - 1) : e.key === "Home" ? 0 : e.key === "End" ? last : null;
    const target = to === null ? undefined : VIEWS[to];
    if (to === null || !target) return;
    e.preventDefault();
    go(target.id);
    tabs.current[to]?.focus();
  }

  if (problem) {
    const missing = problem.status === 404 || problem.status === 422; // an unknown name, or one that cannot be a name
    return (
      <section className="hero" aria-labelledby="h-gone">
        <p className="eyebrow">Try it</p>
        <h1 id="h-gone">{missing ? "We have no demo venue by that name." : "This demo venue is not available right now."}</h1>
        <p>{missing ? "The venues we have are on the Try it page." : problem.detail}</p>
        <div className="row row--wrap">
          <Link className="btn btn--primary" href="/try">
            See the demo venues
          </Link>
        </div>
      </section>
    );
  }
  if (!venue) return <Loading label="Opening the venue…" />;

  const s = venue.summary;
  const since = refreshedOn(venue.refreshed_at);
  const facts = [
    s.events != null ? `${s.events} events` : null,
    matched(s),
    years(s),
  ].filter(Boolean);

  return (
    <>
      <section className="hero" aria-labelledby="h-venue">
        <p className="eyebrow">Demo venue · {venue.city}</p>
        <h1 id="h-venue">{venue.name}</h1>
        <p>{venue.blurb}</p>
        <div className="row row--wrap">
          <Label kind="modelled" detail="public lineups" />
          {facts.length ? <span className="meta">{facts.join(" · ")}</span> : null}
          {since ? <span className="meta">Rebuilt {since}</span> : null}
        </div>
      </section>

      <div>
        <div className="tabs" role="tablist" aria-label="What to look at">
          {VIEWS.map((v, i) => (
            <button
              key={v.id}
              ref={(el) => {
                tabs.current[i] = el;
              }}
              className="tab"
              role="tab"
              type="button"
              id={`tab-${v.id}`}
              aria-selected={view === v.id}
              aria-controls={`panel-${v.id}`}
              tabIndex={view === v.id ? 0 : -1}
              onClick={() => go(v.id)}
              onKeyDown={(e) => onKey(e, i)}
            >
              {v.label}
            </button>
          ))}
        </div>
        <div role="tabpanel" id={`panel-${view}`} aria-labelledby={`tab-${view}`} tabIndex={0} style={{ paddingTop: "var(--s-5)", display: "grid", gap: "var(--s-5)" }}>
          {view === "soundcheck" ? <SoundcheckWorkspace base={base} canWrite={false} demo /> : null}
          {view === "map" ? <MapWorkspace base={base} demo /> : null}
          {view === "brief" ? <BriefWorkspace base={base} canWrite={false} demo /> : null}
        </div>
      </div>

      <section className="card" aria-labelledby="h-own">
        <h2 className="card__title" id="h-own" style={{ marginBottom: "var(--s-3)" }}>
          Like what you see? Run it on your own room.
        </h2>
        <p style={{ marginBottom: "var(--s-4)" }}>
          This venue is read from public lineups, so its scores are provisional. With your guests’ own favourites behind it, the same Soundcheck is
          measured against the people who actually come.
        </p>
        <div className="row row--wrap">
          <Link className="btn btn--primary" href="/signup">
            Create an account
          </Link>
          <Link className="btn" href="/try">
            Other demo venues
          </Link>
        </div>
      </section>
    </>
  );
}
