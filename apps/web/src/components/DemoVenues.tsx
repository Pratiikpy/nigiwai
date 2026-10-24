"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { Icon } from "@/components/Icon";
import { Label } from "@/components/Label";
import { Loading, Notice } from "@/components/owner/ui";
import { api } from "@/lib/api";
import { type DemoVenue, matched, years } from "@/lib/demo";

/** The demo venues anyone can open without an account, as cards. Each is built from the room's public event lineups. */
export function DemoVenues() {
  const [venues, setVenues] = useState<DemoVenue[] | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let live = true;
    api<DemoVenue[]>("/public/demo")
      .then((v) => live && setVenues(v))
      .catch(() => live && setFailed(true));
    return () => {
      live = false;
    };
  }, []);

  if (failed) return <Notice tone="error">The demo venues could not be loaded. Please reload the page in a moment.</Notice>;
  if (!venues) return <Loading label="Loading the demo venues…" />;
  if (venues.length === 0) {
    return <Notice tone="warn">The demo venues are being prepared. Please check back shortly.</Notice>;
  }
  return (
    <div className="venues" data-testid="venues">
      {venues.map((v) => {
        const m = matched(v.summary);
        const y = years(v.summary);
        return (
          <Link key={v.slug} className="card vcard" href={`/try/${v.slug}`} data-testid="venue-card">
            <div className="row row--wrap">
              <Label kind="modelled" detail="public lineups" />
            </div>
            <h3>{v.name}</h3>
            <dl>
              <dt>Where</dt>
              <dd>{v.city}</dd>
              {v.summary.events != null ? (
                <>
                  <dt>Events used</dt>
                  <dd>{v.summary.events}</dd>
                </>
              ) : null}
              {m ? (
                <>
                  <dt>Performers</dt>
                  <dd>{m}</dd>
                </>
              ) : null}
              {y ? (
                <>
                  <dt>Years</dt>
                  <dd>{y}</dd>
                </>
              ) : null}
            </dl>
            <span className="btn btn--sm">
              Open <Icon name="arrow-r" size="sm" />
            </span>
          </Link>
        );
      })}
    </div>
  );
}
