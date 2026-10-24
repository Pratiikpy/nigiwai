"use client";

import { useEffect, useState } from "react";
import { BriefSheet } from "@/components/BriefSheet";
import { Icon } from "@/components/Icon";
import { Loading, Notice } from "@/components/owner/ui";
import { ApiError, api } from "@/lib/api";
import type { Brief } from "@/lib/brief";

/** A brief opened from a share link: read-only, no account, and a plain message when the link is off or has expired. */
export function SharedBrief({ token }: { token: string }) {
  const [doc, setDoc] = useState<Brief | null>(null);
  const [gone, setGone] = useState<string | null>(null);

  useEffect(() => {
    let live = true;
    api<Brief>(`/public/brief/${encodeURIComponent(token)}`)
      .then((d) => live && setDoc(d))
      .catch((e: unknown) => live && setGone(e instanceof ApiError && e.status === 404 ? e.detail : "We couldn’t load this brief. Please try again."));
    return () => {
      live = false;
    };
  }, [token]);

  if (gone) {
    return (
      <div className="sheetwrap">
        <Notice tone="warn">
          <strong>{gone}</strong> Ask whoever sent it for a new link.
        </Notice>
      </div>
    );
  }
  if (!doc) return <Loading />;
  return (
    <div className="sheetwrap">
      <div className="row row--wrap noprint">
        <a className="btn btn--primary" href={`/api/v1/public/brief/${encodeURIComponent(token)}/pdf`} download>
          <Icon name="download" />
          Save as PDF
        </a>
      </div>
      <BriefSheet doc={doc} />
      {doc.expires_at ? <p className="meta noprint">This link works until {new Date(doc.expires_at).toLocaleDateString()}.</p> : null}
    </div>
  );
}
