"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { Icon } from "@/components/Icon";
import { Notice } from "@/components/owner/ui";
import { ApiError, api } from "@/lib/api";
import { type FoundPlace, placeLine } from "@/lib/demo";

/**
 * Try any venue: look a room up on MusicBrainz by name and ask for it to be built from its public lineups, the same way the
 * prepared ones are. The build takes minutes and runs in the background, so asking leads to the venue's own page, which shows
 * how far it has got.
 */
export function FindVenue() {
  const router = useRouter();
  const [query, setQuery] = useState("");
  const [hits, setHits] = useState<FoundPlace[] | null>(null);
  const [searched, setSearched] = useState("");
  const [searching, setSearching] = useState(false);
  const [asking, setAsking] = useState<string | null>(null);
  const [problem, setProblem] = useState<string | null>(null);

  async function search(event: React.FormEvent) {
    event.preventDefault();
    const q = query.trim();
    if (searching || q.length < 3) return;
    setSearching(true);
    setProblem(null);
    try {
      const out = await api<{ places: FoundPlace[] }>(`/public/demo/find?q=${encodeURIComponent(q)}`);
      setHits(out.places);
      setSearched(q);
    } catch (e) {
      setHits(null);
      setProblem(e instanceof ApiError ? e.detail : "The search didn’t work. Please try again.");
    } finally {
      setSearching(false);
    }
  }

  async function ask(place: FoundPlace) {
    if (asking) return;
    setAsking(place.mbid);
    setProblem(null);
    try {
      const out = await api<{ slug: string; status: string }>("/public/demo/request", { method: "POST", body: { mbid: place.mbid } });
      router.push(`/try/${out.slug}`);
    } catch (e) {
      setProblem(e instanceof ApiError ? e.detail : "We couldn’t start that. Please try again.");
      setAsking(null);
    }
  }

  return (
    <section className="card stack" aria-labelledby="h-find" data-testid="find-venue">
      <div>
        <h2 className="card__title" id="h-find">
          Or try any venue
        </h2>
        <p className="muted" style={{ marginTop: "var(--s-2)" }}>
          Search for a music venue by name. We read who has played there from public event listings, match the acts in Qloo and build the
          same Soundcheck you see above. It takes a few minutes. The venue is kept for seven days, then deleted.
        </p>
      </div>
      <form className="stack stack--sm" onSubmit={search}>
        <div className="field">
          <label htmlFor="find-q">Venue name</label>
          <div className="findrow">
            <input
              id="find-q"
              className="input"
              type="search"
              value={query}
              maxLength={80}
              autoComplete="off"
              placeholder="Schubas Tavern"
              onChange={(e) => setQuery(e.target.value)}
            />
            <button className="btn" type="submit" disabled={searching || query.trim().length < 3}>
              <Icon name="search" size="sm" />
              {searching ? "Searching…" : "Search"}
            </button>
          </div>
        </div>
      </form>
      {problem ? <Notice tone="error">{problem}</Notice> : null}
      {hits ? (
        hits.length ? (
          <ul className="stack stack--sm" role="list" aria-label="Matching venues">
            {hits.map((h) => (
              <li key={h.mbid} className="qr-item" data-testid="found-place">
                <div className="qr-item__top">
                  <div>
                    <strong>{h.name}</strong>
                    <span className="meta">{placeLine(h) || "No address listed"}</span>
                    {h.slug && h.status === "ready" ? <span className="meta">Already built.</span> : null}
                    {h.slug && h.status === "building" ? <span className="meta">Being built now.</span> : null}
                    {!h.mappable ? <span className="meta">MusicBrainz has no position for this venue, so it cannot be placed on a map.</span> : null}
                  </div>
                  {h.slug && h.status !== "failed" ? (
                    <Link className="btn btn--sm btn--primary" href={`/try/${h.slug}`}>
                      {h.status === "ready" ? "Open" : "See progress"}
                      <Icon name="arrow-r" size="sm" />
                    </Link>
                  ) : h.mappable ? (
                    <button className="btn btn--sm btn--primary" type="button" onClick={() => void ask(h)} disabled={asking !== null}>
                      {asking === h.mbid ? "Starting…" : h.status === "failed" ? "Try again" : "Build this venue"}
                    </button>
                  ) : null}
                </div>
              </li>
            ))}
          </ul>
        ) : (
          <p className="meta" data-testid="no-places">
            MusicBrainz has no venue called “{searched}”. Try a shorter name.
          </p>
        )
      ) : null}
      <p className="meta">
        A venue needs at least 10 past events with lineups on MusicBrainz and at least 15 of its acts that Qloo knows; if it falls short we say so. Each build makes more than a hundred Qloo calls, so
        the whole site can build only a few new venues a day.
      </p>
    </section>
  );
}
