"use client";

import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { type KeyboardEvent, useEffect, useRef, useState } from "react";
import { Icon } from "@/components/Icon";
import { Label } from "@/components/Label";
import { BriefWorkspace } from "@/components/owner/BriefWorkspace";
import { GrowWorkspace } from "@/components/owner/GrowWorkspace";
import { MapWorkspace } from "@/components/owner/MapWorkspace";
import { SoundWorkspace } from "@/components/owner/SoundWorkspace";
import { SoundcheckWorkspace } from "@/components/owner/SoundcheckWorkspace";
import { Loading, Notice } from "@/components/owner/ui";
import { ApiError, api } from "@/lib/api";
import { type DemoVenue, type RequestStatus, demoBase, isRequested, matched, refreshedOn, timeOn, years } from "@/lib/demo";

const VIEWS = [
  { id: "soundcheck", label: "Soundcheck" },
  { id: "sound", label: "Sound plan" },
  { id: "grow", label: "Grow" },
  { id: "map", label: "Crowd map" },
  { id: "brief", label: "Booking Brief" },
] as const;
type View = (typeof VIEWS)[number]["id"];

function parseView(raw: string | null): View {
  return VIEWS.find((v) => v.id === raw)?.id ?? "soundcheck";
}

/** One demo venue: the same workspaces an owner has, pointed at the venue's public routes. */
export function TryVenue({ slug }: { slug: string }) {
  const router = useRouter();
  const path = usePathname();
  const params = useSearchParams();
  const view = parseView(params.get("tab"));
  const [venue, setVenue] = useState<DemoVenue | null>(null);
  const [problem, setProblem] = useState<{ status: number; detail: string } | null>(null);
  // A venue someone asked for is not open until its build has finished; this is where that build stands.
  const [pending, setPending] = useState<RequestStatus | null>(null);
  const [checkedAt, setCheckedAt] = useState<string | null>(null);
  const [again, setAgain] = useState<{ busy: boolean; note: string | null }>({ busy: false, note: null });
  const [tick, setTick] = useState(0);
  const building = useRef(false);
  const tabs = useRef<Array<HTMLButtonElement | null>>([]);
  const base = demoBase(slug);

  useEffect(() => {
    let live = true;
    api<DemoVenue>(base)
      .then((v) => {
        if (!live) return;
        building.current = false;
        setPending(null);
        setVenue(v);
      })
      .catch(async (e: unknown) => {
        if (!live) return;
        // A requested venue answers "not available" while it builds and after it fails; its status route says which.
        if (e instanceof ApiError && e.status === 503 && isRequested(slug)) {
          try {
            const s = await api<RequestStatus>(`/public/demo/request/${slug}`);
            if (!live) return;
            building.current = s.status === "building";
            setPending(s);
            setCheckedAt(new Date().toISOString());
            return;
          } catch {
            // the status could not be read either: fall through to the general message
          }
        }
        // While a build is being watched, one failed check is not the end of it: the next one tries again.
        if (building.current && !(e instanceof ApiError && e.status === 404)) return;
        setProblem(
          e instanceof ApiError
            ? { status: e.status, detail: e.message }
            : { status: 0, detail: "The demo could not be reached. Please reload the page in a moment." },
        );
      });
    return () => {
      live = false;
    };
  }, [base, slug, tick]);

  const waiting = pending?.status === "building";
  useEffect(() => {
    if (!waiting) return;
    const timer = setInterval(() => setTick((t) => t + 1), 4000);
    return () => clearInterval(timer);
  }, [waiting]);

  async function askAgain(mbid: string) {
    setAgain({ busy: true, note: null });
    try {
      const out = await api<{ slug: string; status: string }>("/public/demo/request", { method: "POST", body: { mbid } });
      if (out.status === "building") {
        setProblem(null);
        setTick((t) => t + 1);
        setAgain({ busy: false, note: null });
      } else {
        setAgain({ busy: false, note: "That venue was tried a moment ago. Please wait before asking again." });
      }
    } catch (e) {
      setAgain({ busy: false, note: e instanceof ApiError ? e.detail : "We couldn’t start that. Please try again." });
    }
  }

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
    tabs.current[to]?.scrollIntoView({ inline: "nearest", block: "nearest" });
  }

  if (pending && pending.status === "building") {
    const checked = timeOn(checkedAt);
    return (
      <>
        <section className="hero" aria-labelledby="h-building" data-testid="venue-building">
          <p className="eyebrow">Building a venue</p>
          <h1 id="h-building">{pending.name}</h1>
          <p>
            We are reading who has played here from public event listings and matching the acts in Qloo. It takes a few minutes. You can leave this page
            open, or come back to this address: the venue is kept for seven days.
          </p>
          <Loading label={checked ? `Still building. Last checked at ${checked}.` : "Building the venue…"} />
        </section>
        <section className="card" aria-labelledby="h-steps">
          <h2 className="card__title" id="h-steps" style={{ marginBottom: "var(--s-3)" }}>
            What is happening
          </h2>
          <ul className="ticks">
            {[
              "The past events and their lineups come from MusicBrainz, which is public domain.",
              "Each act is looked up in Qloo by exact name. An act Qloo does not hold is left out, never guessed.",
              "Acts that share tastes are grouped into scenes, then acts are suggested and scored against them.",
            ].map((t) => (
              <li key={t}>
                <Icon name="check" />
                {t}
              </li>
            ))}
          </ul>
        </section>
      </>
    );
  }
  if (pending && pending.status === "failed" && !problem) {
    const at = pending.retry_at ? new Date(pending.retry_at) : null;
    // judged against the moment the status was read, so the page does not read the clock while rendering
    const waitUntil = at && checkedAt && at.getTime() > new Date(checkedAt).getTime() ? timeOn(pending.retry_at) : null;
    return (
      <section className="hero" aria-labelledby="h-failed" data-testid="venue-failed">
        <p className="eyebrow">Try it</p>
        <h1 id="h-failed">We couldn’t build {pending.name}.</h1>
        <p>{pending.reason}</p>
        {again.note ? <Notice tone="warn">{again.note}</Notice> : null}
        <div className="row row--wrap">
          <Link className="btn btn--primary" href="/try">
            Try another venue
          </Link>
          {pending.mbid ? (
            <button className="btn" type="button" disabled={again.busy || waitUntil !== null} onClick={() => void askAgain(pending.mbid as string)}>
              {again.busy ? "Starting…" : "Ask again"}
            </button>
          ) : null}
          {waitUntil ? <span className="meta">You can ask again after {waitUntil}.</span> : null}
        </div>
      </section>
    );
  }
  if (problem) {
    const missing = problem.status === 404 || problem.status === 422; // an unknown name, or one that cannot be a name
    const gone = missing && isRequested(slug);
    return (
      <section className="hero" aria-labelledby="h-gone">
        <p className="eyebrow">Try it</p>
        <h1 id="h-gone">
          {gone ? "This venue is gone." : missing ? "We have no demo venue by that name." : "This demo venue is not available right now."}
        </h1>
        <p>
          {gone
            ? "A venue someone asks for is kept for seven days, then deleted. You can ask for it again on the Try it page."
            : missing
              ? "The venues we have are on the Try it page."
              : problem.detail}
        </p>
        <div className="row row--wrap">
          <Link className="btn btn--primary" href="/try">
            See the demo venues
          </Link>
        </div>
      </section>
    );
  }
  // Tall enough that the footer starts below the fold: when the venue arrives it then has nothing visible to push down.
  if (!venue)
    return (
      <div className="pub-loading">
        <Loading label="Opening the venue…" />
      </div>
    );

  const s = venue.summary;
  const since = refreshedOn(venue.refreshed_at);
  const keptUntil = refreshedOn(venue.expires_at);
  const facts = [
    s.events != null ? `${s.events} events` : null,
    matched(s),
    years(s),
  ].filter(Boolean);

  return (
    <>
      <section className="hero" aria-labelledby="h-venue">
        <p className="eyebrow">
          {venue.requested ? "Venue you asked for" : "Demo venue"}
          {venue.city ? ` · ${venue.city}` : ""}
        </p>
        <h1 id="h-venue">{venue.name}</h1>
        <p>{venue.blurb}</p>
        <div className="row row--wrap">
          <Label kind="modelled" detail="public lineups" />
          {facts.length ? <span className="meta">{facts.join(" · ")}</span> : null}
          {since ? <span className="meta">{venue.requested ? "Built" : "Rebuilt"} {since}</span> : null}
        </div>
        {venue.requested && keptUntil ? (
          <Notice tone="sample">
            Built from this room’s public lineups when someone asked for it. It is kept until {keptUntil}, then deleted. Anyone with this address can open it until then.
          </Notice>
        ) : null}
      </section>

      <div style={{ minWidth: 0 }}>
        <div className="tabs tabs--scroll" role="tablist" aria-label="What to look at">
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
        <div role="tabpanel" id={`panel-${view}`} aria-labelledby={`tab-${view}`} tabIndex={0} style={{ paddingTop: "var(--s-5)", display: "grid", gap: "var(--s-5)", alignContent: "start", minHeight: "80svh" }}>
          {view === "soundcheck" ? <SoundcheckWorkspace base={base} canWrite={false} demo /> : null}
          {view === "sound" ? <SoundWorkspace base={base} canWrite={false} soundcheckLink={`/try/${slug}`} /> : null}
          {view === "grow" ? <GrowWorkspace base={base} canWrite={false} soundcheckLink={`/try/${slug}`} /> : null}
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
