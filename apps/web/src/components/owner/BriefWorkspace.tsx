"use client";

import { useCallback, useEffect, useState } from "react";
import { BriefSheet } from "@/components/BriefSheet";
import { Icon } from "@/components/Icon";
import { Feedback } from "@/components/owner/Feedback";
import { Loading, Notice, PageHead } from "@/components/owner/ui";
import { ApiError, api } from "@/lib/api";
import type { Brief, Share } from "@/lib/brief";

/** The Booking Brief for one venue. A public demo venue shows the sheet and the PDF but cannot create share links. */
export function BriefWorkspace({ base, canWrite, demo = false }: { base: string; canWrite: boolean; demo?: boolean }) {
  const [doc, setDoc] = useState<Brief | null>(null);
  const [shares, setShares] = useState<Share[]>([]);
  const [link, setLink] = useState<string | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);
  const [busy, setBusy] = useState(false);

  const fail = (e: unknown, fallback: string) => setProblem(e instanceof ApiError ? e.detail : fallback);

  useEffect(() => {
    let live = true;
    Promise.all([api<Brief>(`${base}/brief`), demo ? Promise.resolve<Share[]>([]) : api<Share[]>(`${base}/brief/shares`)])
      .then(([d, s]) => {
        if (!live) return;
        setDoc(d);
        setShares(s);
      })
      .catch((e: unknown) => live && fail(e, "We couldn’t load the brief."));
    return () => {
      live = false;
    };
  }, [base, demo]);

  const share = useCallback(async () => {
    setBusy(true);
    setProblem(null);
    try {
      const made = await api<{ id: string; url: string }>(`${base}/brief/shares`, { method: "POST" });
      setLink(made.url);
      setShares(await api<Share[]>(`${base}/brief/shares`));
    } catch (e) {
      fail(e, "We couldn’t make a link.");
    } finally {
      setBusy(false);
    }
  }, [base]);

  const revoke = async (id: string) => {
    try {
      await api(`${base}/brief/shares/${id}`, { method: "DELETE" });
      setShares(await api<Share[]>(`${base}/brief/shares`));
      setLink(null);
    } catch (e) {
      fail(e, "We couldn’t turn that link off.");
    }
  };

  if (!doc) return problem ? <Notice tone="error">{problem}</Notice> : <Loading />;

  const liveShares = shares.filter((s) => s.live);
  return (
    <>
      {demo ? null : (
        <PageHead
          title="Booking Brief"
          lead="One page you can forward to a booker or a partner, drawn from your crowd and Soundcheck. Names and our own scores only."
        />
      )}
      {problem ? <Notice tone="error">{problem}</Notice> : null}
      <div className="sheetwrap">
        <div className="row row--wrap noprint">
          <a className="btn btn--primary" href={`/api/v1${base}/brief.pdf`} download data-testid="pdf">
            <Icon name="download" />
            Save as PDF
          </a>
          {canWrite && !demo ? (
            <button className="btn" type="button" onClick={() => void share()} disabled={busy || doc.status !== "ok"}>
              <Icon name="share" />
              Create a share link
            </button>
          ) : null}
        </div>
        {link ? (
          <div className="banner noprint" data-tone="ok" role="status" data-testid="share-link">
            <Icon name="check" />
            <div className="banner__body">
              <strong>Share link created.</strong> It shows this brief as it is now, expires in 30 days and can be turned off below.
              <br />
              <span className="mono" style={{ overflowWrap: "anywhere" }}>
                {link}
              </span>{" "}
              <button
                className="btn btn--sm"
                type="button"
                onClick={() => {
                  void navigator.clipboard?.writeText(link).then(() => setCopied(true));
                }}
              >
                <Icon name="copy" size="sm" />
                {copied ? "Copied" : "Copy"}
              </button>
            </div>
          </div>
        ) : null}
        <BriefSheet doc={doc} />
        {doc.status === "ok" && !demo ? <Feedback kind="brief" /> : null}
        {liveShares.length ? (
          <section className="stack noprint" aria-labelledby="h-shares" style={{ width: "100%", maxWidth: 794 }}>
            <h2 id="h-shares">Links that are on</h2>
            <ul className="stack stack--sm" role="list">
              {liveShares.map((s) => (
                <li key={s.id} className="row row--between row--wrap">
                  <span className="meta">
                    Made {new Date(s.created_at).toLocaleDateString()}, expires {new Date(s.expires_at).toLocaleDateString()}
                  </span>
                  {canWrite ? (
                    <button className="btn btn--sm btn--ghost" type="button" onClick={() => void revoke(s.id)}>
                      Turn off
                    </button>
                  ) : null}
                </li>
              ))}
            </ul>
          </section>
        ) : null}
      </div>
    </>
  );
}
