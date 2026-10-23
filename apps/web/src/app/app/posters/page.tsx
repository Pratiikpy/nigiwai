"use client";

import Link from "next/link";
import QRCode from "qrcode";
import { useEffect, useState } from "react";
import { Icon } from "@/components/Icon";
import { Loading, Notice, PageHead } from "@/components/owner/ui";
import { ApiError, api, type QrPoint } from "@/lib/api";
import { useVenue } from "@/lib/venue";

export default function PostersPage() {
  const { venue, error, tenantPath, reload, canWrite } = useVenue();
  const [label, setLabel] = useState("");
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);

  if (error) return <Notice tone="error">{error}</Notice>;
  if (!venue) return <Loading />;
  if (!venue.location) {
    return (
      <>
        <PageHead title="QR posters" />
        <Notice tone="warn">
          Describe your venue first. <Link href="/app/venue">Go to your venue</Link>
        </Notice>
      </>
    );
  }
  const location = venue.location;
  const published = venue.survey?.status === "published";

  const create = async (event: React.FormEvent) => {
    event.preventDefault();
    if (busy || !label.trim()) return;
    setBusy(true);
    setProblem(null);
    try {
      await api<QrPoint>(`${tenantPath}/locations/${location.id}/qr-points`, { method: "POST", body: { label: label.trim() } });
      setLabel("");
      await reload();
    } catch (e) {
      setProblem(e instanceof ApiError ? e.detail : "We couldn't create that. Please try again.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <>
      <PageHead
        title="QR posters"
        lead="One code per spot, such as the bar or a table group. Each shows up separately in your counts, so you can see where guests answer."
      />
      {!published ? (
        <Notice tone="warn">
          Your survey isn&rsquo;t published yet, so a scanned code will say it&rsquo;s closed. <Link href="/app/survey">Publish it</Link>
        </Notice>
      ) : null}

      {canWrite ? (
        <form className="card stack" onSubmit={create}>
          <h2 className="card__title">New code</h2>
          <div className="field">
            <label htmlFor="qr-label">Where will it go?</label>
            <input className="input" id="qr-label" maxLength={120} placeholder="Bar end" value={label} onChange={(e) => setLabel(e.target.value)} />
          </div>
          {problem ? <Notice tone="error">{problem}</Notice> : null}
          <div>
            <button className="btn btn--primary" type="submit" disabled={busy || !label.trim()}>
              <Icon name="plus" size="sm" />
              {busy ? "Creating…" : "Create code"}
            </button>
          </div>
        </form>
      ) : null}

      {venue.qrPoints.length === 0 ? (
        <div className="card card--flat">
          <div className="empty empty--inline">
            <h2>No codes yet.</h2>
            <p>Create your first one above, then print the poster.</p>
          </div>
        </div>
      ) : (
        <ul className="qr-list" role="list">
          {venue.qrPoints.map((point) => (
            <QrItem key={point.id} point={point} tenantPath={tenantPath} canWrite={canWrite} onChange={reload} />
          ))}
        </ul>
      )}
    </>
  );
}

function QrItem({
  point,
  tenantPath,
  canWrite,
  onChange,
}: {
  point: QrPoint;
  tenantPath: string;
  canWrite: boolean;
  onChange: () => Promise<void>;
}) {
  const [svg, setSvg] = useState<string | null>(null);
  const [confirm, setConfirm] = useState<"rotate" | "revoke" | null>(null);
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);
  const active = point.status === "active";

  useEffect(() => {
    let live = true;
    if (!point.url || !active) return;
    QRCode.toString(point.url, { type: "svg", errorCorrectionLevel: "Q", margin: 1, width: 132 })
      .then((out) => live && setSvg(out))
      .catch(() => live && setSvg(null));
    return () => {
      live = false;
    };
  }, [point.url, active]);

  const act = async (what: "rotate" | "revoke") => {
    setBusy(true);
    setProblem(null);
    try {
      await api<QrPoint>(`${tenantPath}/qr-points/${point.id}/${what}`, { method: "POST" });
      setConfirm(null);
      await onChange();
    } catch (e) {
      setProblem(e instanceof ApiError ? e.detail : "That didn't work. Please try again.");
    } finally {
      setBusy(false);
    }
  };

  const copy = async () => {
    if (!point.url) return;
    try {
      await navigator.clipboard.writeText(point.url);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      /* the address is selectable text */
    }
  };

  return (
    <li className="qr-item" data-status={point.status}>
      <div className="qr-item__top">
        <div>
          <h2 className="card__title">{point.label}</h2>
          <span className="meta">ends …{point.token_hint}</span>
        </div>
        <span className="pill" data-tone={active ? undefined : "muted"}>
          {active ? "Active" : "Revoked"}
        </span>
      </div>

      <div className="row row--wrap" style={{ gap: "var(--s-5)", alignItems: "flex-start" }}>
        {svg ? (
          <div
            role="img"
            aria-label={`QR code for ${point.label}`}
            style={{ width: 132, height: 132, background: "#fff", borderRadius: "var(--r-sm)", flex: "none", padding: 4 }}
            dangerouslySetInnerHTML={{ __html: svg }}
          />
        ) : null}
        <div className="stack stack--sm grow" style={{ minWidth: 220 }}>
          {point.url ? <p className="qr-item__url">{point.url}</p> : null}
          {active && point.url ? (
            <div className="row row--wrap">
              <a className="btn btn--sm btn--primary" href={`/api/v1${tenantPath}/qr-points/${point.id}/poster.pdf?size=a4`} target="_blank" rel="noreferrer">
                <Icon name="download" size="sm" />A4 poster
              </a>
              <a className="btn btn--sm" href={`/api/v1${tenantPath}/qr-points/${point.id}/poster.pdf?size=a6`} target="_blank" rel="noreferrer">
                <Icon name="download" size="sm" />A6 table card
              </a>
              <button className="btn btn--sm" type="button" onClick={() => void copy()}>
                <Icon name={copied ? "check" : "copy"} size="sm" />
                {copied ? "Copied" : "Copy link"}
              </button>
              <a className="btn btn--sm btn--ghost" href={point.url.replace(/^https?:\/\/[^/]+/, "")} target="_blank" rel="noreferrer">
                <Icon name="ext" size="sm" />
                Open survey
              </a>
            </div>
          ) : null}
        </div>
      </div>

      {canWrite ? (
        confirm ? (
          <div className="banner" data-tone="warn" role="alertdialog" aria-label={`Confirm ${confirm}`}>
            <Icon name="alert" />
            <div className="banner__body">
              {confirm === "rotate" ? (
                <>
                  <strong>Replace this code?</strong>A new secret is made and every printed copy of the old code stops
                  working at once.
                </>
              ) : (
                <>
                  <strong>Turn this code off?</strong>Anyone who scans it will be told the survey is closed. You can
                  bring it back later by replacing it.
                </>
              )}
            </div>
            <div className="row row--wrap" style={{ marginLeft: "calc(20px + var(--s-3))" }}>
              <button className="btn btn--sm btn--danger" type="button" disabled={busy} onClick={() => void act(confirm)}>
                {busy ? "Working…" : confirm === "rotate" ? "Replace it" : "Turn it off"}
              </button>
              <button className="btn btn--sm" type="button" disabled={busy} onClick={() => setConfirm(null)}>
                Cancel
              </button>
            </div>
          </div>
        ) : (
          <div className="row row--wrap">
            <button className="btn btn--sm" type="button" onClick={() => setConfirm("rotate")}>
              <Icon name="refresh" size="sm" />
              {active ? "Replace code" : "Bring back with a new code"}
            </button>
            {active ? (
              <button className="btn btn--sm btn--ghost" type="button" onClick={() => setConfirm("revoke")}>
                <Icon name="pause" size="sm" />
                Turn off
              </button>
            ) : null}
          </div>
        )
      ) : null}
      {problem ? <Notice tone="error">{problem}</Notice> : null}
    </li>
  );
}
