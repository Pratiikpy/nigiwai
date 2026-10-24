"use client";

import { useCallback, useEffect, useState } from "react";
import { Icon } from "@/components/Icon";
import { Label } from "@/components/Label";
import { Sheet } from "@/components/Sheet";
import { ApiError, api, apiBlob, type CardExtras, type PickerType, type Reward, type TasteCardData } from "@/lib/api";
import { CATEGORIES } from "@/lib/survey";
import { Tile } from "./Tile";

const KINDS = new Set(Object.keys(CATEGORIES));
const toKind = (urn: string): PickerType | null => {
  const k = urn.split(":").pop() ?? "";
  return KINDS.has(k) ? (k as PickerType) : null;
};

function Distance({ m }: { m: number | null | undefined }) {
  if (m == null) return null;
  return <>{m < 1000 ? `${Math.round(m / 10) * 10} m` : `${(m / 1000).toFixed(1)} km`}</>;
}

/**
 * The card a guest sees after sending. The simple card arrives at once (no Qloo call). Related tastes and places
 * near the venue fill in afterwards, and when they are slow or unavailable the simple card simply stays.
 */
export function TasteCard({
  receipt,
  reward,
  onRemove,
  onShare,
  businessName,
}: {
  receipt: string;
  reward: Reward | null;
  onRemove: () => void;
  onShare: () => void;
  businessName: string;
}) {
  const [card, setCard] = useState<TasteCardData | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  const [extras, setExtras] = useState<CardExtras | "loading" | null>(null);
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    let live = true;
    api<TasteCardData>("/public/card", { method: "POST", body: { receipt } })
      .then((c) => live && setCard(c))
      .catch((e: unknown) => live && setProblem(e instanceof ApiError ? e.detail : "Something went wrong."));
    return () => {
      live = false;
    };
  }, [receipt]);

  const [attempt, setAttempt] = useState(0);
  const fill = card?.can_fill_in === true;
  useEffect(() => {
    if (!fill) return;
    let live = true;
    api<CardExtras>("/public/card/extras", { method: "POST", body: { receipt } })
      .then((x) => live && setExtras(x))
      .catch(() => live && setExtras({ status: "unavailable", related: [], near: [] }));
    return () => {
      live = false;
    };
  }, [fill, receipt, attempt]);
  const retry = useCallback(() => {
    setExtras("loading");
    setAttempt((a) => a + 1);
  }, []);

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(receipt);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      /* the code is selectable text */
    }
  };

  if (problem) {
    return (
      <section className="done" aria-labelledby="h-done">
        <h1 className="display done__h" id="h-done">
          Thank you.
        </h1>
        <div className="banner" data-tone="warn" role="status">
          <Icon name="alert" />
          <div className="banner__body">
            <strong>Your answers are saved.</strong>
            We couldn&rsquo;t build your card just now. {problem}
          </div>
        </div>
        <ReceiptBlock receipt={receipt} copied={copied} onCopy={() => void copy()} onRemove={onRemove} />
      </section>
    );
  }
  if (!card) {
    return (
      <section className="tastecard" aria-busy="true" aria-label="Your Taste Card">
        <div className="res-status" role="status">
          <span className="spin" aria-hidden="true" />
          Building your card…
        </div>
        <span className="skel" style={{ height: 180, borderRadius: "var(--card-r)" }} />
      </section>
    );
  }

  const g = card.group;
  const needMore = g.status === "forming";
  return (
    <article className="tastecard" aria-labelledby="tc-title">
      <div className="tc-head">
        <p className="eyebrow">Taste Card · {businessName}</p>
      </div>

      <div className="tc-group">
        <p className="tc-group__lead">
          {needMore ? "Your picks are in. The crowd here is" : "People who picked similar things here also pick"}
        </p>
        <h1 className="display tc-title" id="tc-title">
          {needMore ? "still forming" : g.label}
        </h1>
        <p className="tc-group__sub">
          {needMore
            ? `${g.n} ${g.n === 1 ? "guest has" : "guests have"} answered so far. Groups appear at ${g.needed ?? 60}, and yours will be counted when they do.`
            : g.share_text}
        </p>
        <div className="lbl-set">
          {needMore ? null : <Label kind="measured" detail={`${g.n} guests`} />}
          {!needMore && g.provisional ? <Label kind="modelled" detail="early read" /> : null}
        </div>
      </div>

      <section className="tc-sec" aria-labelledby="tc-h-picks">
        <h2 className="tc-h" id="tc-h-picks">
          {needMore ? "Your picks" : "Your strongest picks"}
        </h2>
        <ul className="tc-picks">
          {card.picks.map((p) => {
            const kind = toKind(p.type);
            return (
              <li key={p.entity_id}>
                {kind ? <Tile name={p.name} type={kind} /> : null}
                <span>{p.name}</span>
              </li>
            );
          })}
        </ul>
      </section>

      {fill ? (
        <>
          <section className="tc-sec" aria-labelledby="tc-h-map" aria-busy={extras === null || extras === "loading"}>
            <div className="tc-h-row">
              <h2 className="tc-h" id="tc-h-map">
                If you love these, you might also like
              </h2>
              {extras && extras !== "loading" && extras.related.length ? <Label kind="observed" detail="from Qloo" /> : null}
            </div>
            <div className="tmap" aria-live="polite">
              {extras === null || extras === "loading" ? (
                <>
                  <div className="res-status" role="status">
                    <span className="spin" aria-hidden="true" />
                    Finding related tastes…
                  </div>
                  <div className="tmap-load" aria-hidden="true">
                    {[0, 1, 2].map((i) => (
                      <span key={i} className="skel skel--line-l" style={{ height: 34, borderRadius: 17 }} />
                    ))}
                  </div>
                </>
              ) : extras.related.length ? (
                extras.related.map((rel) => (
                  <div className="branch" key={rel.because}>
                    <span className="branch__src">Because you picked {rel.because}</span>
                    <div className="branch__rel">
                      {rel.items.map((i) => {
                        const kind = toKind(i.type);
                        return (
                          <span className="relchip" key={i.entity_id}>
                            {kind ? <Tile name={i.name} type={kind} /> : null}
                            {i.name}
                          </span>
                        );
                      })}
                    </div>
                  </div>
                ))
              ) : (
                <div className="banner" data-tone="warn" role="status">
                  <Icon name="alert" />
                  <div className="banner__body">
                    <strong>{extras.status === "slow" ? "The extras are slow right now." : "The extras aren’t available right now."}</strong>
                    This is your simple card. Related tastes and nearby places show if you try again.
                  </div>
                  <button className="btn btn--sm" type="button" onClick={retry}>
                    <Icon name="refresh" size="sm" />
                    Try again
                  </button>
                </div>
              )}
            </div>
          </section>

          {extras && extras !== "loading" && extras.near.length ? (
            <section className="tc-sec" aria-labelledby="tc-h-near">
              <div className="tc-h-row">
                <h2 className="tc-h" id="tc-h-near">
                  Places near here
                </h2>
                <Label kind="observed" detail="from Qloo" />
              </div>
              <ul className="tnear">
                {extras.near.map((p) => (
                  <li key={p.entity_id}>
                    <Tile name={p.name} type="brand" />
                    <span className="tnear__t">
                      <strong>{p.name}</strong>
                      {p.address ? <span className="meta">{p.address}</span> : null}
                    </span>
                    <span className="tnear__d">
                      <Distance m={p.distance_m} />
                    </span>
                  </li>
                ))}
              </ul>
            </section>
          ) : null}
        </>
      ) : null}

      {reward ? (
        <section className="ticket" aria-labelledby="tk-h">
          <Icon name="gift" size="lg" />
          <div>
            <h2 id="tk-h" className="ticket__h">
              {reward.title}
            </h2>
            <p className="meta">{reward.detail || "Show this screen at the counter."}</p>
          </div>
        </section>
      ) : null}

      <p className="tc-fine">
        This card shows what people with similar picks tend to like. It says nothing about you personally.
      </p>
      <div className="tc-actions">
        <button className="btn btn--primary btn--lg" type="button" onClick={onShare}>
          <Icon name="share" />
          Share my card
        </button>
      </div>

      <ReceiptBlock receipt={receipt} copied={copied} onCopy={() => void copy()} onRemove={onRemove} />
    </article>
  );
}

function ReceiptBlock({
  receipt,
  copied,
  onCopy,
  onRemove,
}: {
  receipt: string;
  copied: boolean;
  onCopy: () => void;
  onRemove: () => void;
}) {
  return (
    <section className="card receipt" aria-labelledby="h-receipt">
      <h2 className="card__title" id="h-receipt">
        Your receipt code
      </h2>
      <p className="receipt__code" data-testid="receipt">
        {receipt}
      </p>
      <p className="meta">
        Keep it if you want to remove your answers later. Nobody can look your answers up by it, and we can&rsquo;t recover it
        if it&rsquo;s lost.
      </p>
      <div className="row row--wrap">
        <button className="btn btn--sm" type="button" onClick={onCopy}>
          <Icon name={copied ? "check" : "copy"} size="sm" />
          {copied ? "Copied" : "Copy code"}
        </button>
        <button className="btn btn--sm btn--ghost" type="button" onClick={onRemove}>
          Remove my answers
        </button>
      </div>
    </section>
  );
}

export function ShareSheet({ open, onClose, receipt }: { open: boolean; onClose: () => void; receipt: string }) {
  const [url, setUrl] = useState<string | null>(null);
  const [blob, setBlob] = useState<Blob | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  const [wasOpen, setWasOpen] = useState(false);

  // Fetch the picture when the sheet opens, and drop it when the sheet closes.
  if (open !== wasOpen) {
    setWasOpen(open);
    if (!open) {
      setUrl(null);
      setBlob(null);
      setProblem(null);
    }
  }
  useEffect(() => {
    if (!open) return;
    let live = true;
    let made: string | null = null;
    apiBlob("/public/card/share", { receipt })
      .then((b) => {
        if (!live) return;
        made = URL.createObjectURL(b);
        setBlob(b);
        setUrl(made);
      })
      .catch((e: unknown) => live && setProblem(e instanceof ApiError ? e.detail : "We couldn't make the picture."));
    return () => {
      live = false;
      if (made) URL.revokeObjectURL(made);
    };
  }, [open, receipt]);

  const canShare = typeof navigator !== "undefined" && typeof navigator.canShare === "function";
  const share = async () => {
    if (!blob) return;
    const file = new File([blob], "nigiwai-taste-card.png", { type: "image/png" });
    try {
      if (navigator.canShare?.({ files: [file] })) await navigator.share({ files: [file], title: "My Taste Card" });
    } catch {
      /* the guest closed the share dialog */
    }
  };

  return (
    <Sheet open={open} onClose={onClose} title="Share your card">
      {problem ? (
        <div className="banner" data-tone="error" role="alert">
          <Icon name="alert" />
          <div className="banner__body">{problem}</div>
        </div>
      ) : url ? (
        // eslint-disable-next-line @next/next/no-img-element -- a blob URL made in this tab; there is nothing for next/image to optimise
        <img
          src={url}
          alt="Your Taste Card: the venue, your group and three of your picks, as text"
          style={{ width: "100%", height: "auto", borderRadius: "var(--r-sm)", border: "2px solid var(--rule-strong)" }}
        />
      ) : (
        <div className="res-status" role="status">
          <span className="spin" aria-hidden="true" />
          Making your picture…
        </div>
      )}
      <p className="meta">The picture holds your group name and three picks as text. No name, no photo, no location.</p>
      <div className="row row--wrap">
        {url ? (
          <a className="btn grow" href={url} download="nigiwai-taste-card.png">
            <Icon name="download" size="sm" />
            Save image
          </a>
        ) : null}
        {canShare && blob ? (
          <button className="btn grow" type="button" onClick={() => void share()}>
            <Icon name="share" size="sm" />
            Share
          </button>
        ) : null}
      </div>
    </Sheet>
  );
}
