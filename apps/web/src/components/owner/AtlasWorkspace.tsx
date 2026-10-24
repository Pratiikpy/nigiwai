"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { Icon } from "@/components/Icon";
import { Label } from "@/components/Label";
import { Loading, Notice, PageHead } from "@/components/owner/ui";
import { ApiError, api } from "@/lib/api";
import { type AtlasDoc, EXAMPLE, percent } from "@/lib/atlas";

function Groups({ doc, example }: { doc: AtlasDoc; example: boolean }) {
  return (
    <div className="stack" data-testid={example ? "example" : "atlas-groups"}>
      {example ? (
        <Notice tone="sample">
          <strong>An example with invented data.</strong> No venue, guest or item below is real. It shows what the page looks like once enough venues near you have joined.
        </Notice>
      ) : (
        <p className="meta" data-testid="atlas-basis">
          {doc.cell_responses} answers from the venues in your neighbourhood that joined
          {doc.built_at ? `, rebuilt ${new Date(doc.built_at).toLocaleString(undefined, { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" })}` : ""}.
        </p>
      )}
      <div className="at-groups">
        {doc.groups.map((g) => (
          <article key={g.type} className="card at-group" data-testid="atlas-group" aria-labelledby={`at-${example ? "x-" : ""}${g.label}`}>
            <div className="gr-head">
              <h3 id={`at-${example ? "x-" : ""}${g.label}`} className="gr-group__t">
                {g.label}
              </h3>
              <Label kind="measured" />
            </div>
            <ol className="at-list">
              {g.items.map((i) => (
                <li key={i.entity_id} data-testid="atlas-item">
                  <span className="at-list__n">
                    <strong>{i.name}</strong>
                    <span className="meta">
                      {percent(i.share)} of answers · {i.responses} guests · {i.venues} venues
                    </span>
                    <span className="meta" data-testid="atlas-own">
                      {i.own === null ? `Fewer than ${doc.limits.responses_per_item} of your guests picked it.` : `${i.own} of your guests picked it.`}
                    </span>
                  </span>
                </li>
              ))}
            </ol>
          </article>
        ))}
      </div>
    </div>
  );
}

export function AtlasWorkspace({ base, canWrite }: { base: string; canWrite: boolean }) {
  const [doc, setDoc] = useState<AtlasDoc | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  const [agree, setAgree] = useState(false);
  const [busy, setBusy] = useState(false);
  const [example, setExample] = useState(false);

  useEffect(() => {
    let live = true;
    api<AtlasDoc>(`${base}/atlas`)
      .then((d) => live && setDoc(d))
      .catch((e: unknown) => live && setProblem(e instanceof ApiError ? e.detail : "We couldn’t load the Atlas."));
    return () => {
      live = false;
    };
  }, [base]);

  const change = (optIn: boolean) => {
    setProblem(null);
    setBusy(true);
    api<AtlasDoc>(`${base}/atlas`, { method: "PUT", body: { opt_in: optIn } })
      .then((d) => {
        setDoc(d);
        setAgree(false);
      })
      .catch((e: unknown) => setProblem(e instanceof ApiError ? e.detail : "We couldn’t save that."))
      .finally(() => setBusy(false));
  };

  if (!doc && !problem) return <Loading />;
  if (!doc) return <Notice tone="error">{problem}</Notice>;
  const lim = doc.limits;

  return (
    <>
      <PageHead
        title="City Taste Atlas"
        lead="What guests pick in your neighbourhood, pooled across venues that chose to take part. It is anonymous, it opens only when enough venues have joined, and it shows nothing to a venue that has not."
      />
      {problem ? <Notice tone="error">{problem}</Notice> : null}

      <section className="card stack" data-testid="atlas-status" data-state={doc.state} aria-labelledby="h-status">
        <h2 id="h-status" className="card__title">
          {doc.state === "no_location"
            ? "Add your address first"
            : doc.state === "not_joined"
              ? "You have not joined"
              : doc.state === "waiting"
                ? "You have joined; the Atlas is not open in your area yet"
                : "You have joined"}
        </h2>
        <p>{doc.reason || (doc.state === "ready" ? "Your neighbourhood is open. These are the items its venues’ guests picked most." : "")}</p>
        {doc.state === "no_location" ? (
          <Link className="btn" href="/app/venue">
            Go to Your venue
          </Link>
        ) : null}
        {doc.state === "not_joined" ? (
          <div className="stack">
            <details className="disc" open>
              <summary>
                <Icon name="chev-r" />
                What joining shares, and what it never does
              </summary>
              <div className="disc__body stack" data-testid="atlas-terms">
                <ul className="ticks">
                  <li>
                    <Icon name="check" />
                    Shared: for each item your guests picked, a count, added to the counts of other venues in the same neighbourhood square (about a kilometre across).
                  </li>
                  <li>
                    <Icon name="shield" />
                    Never shared: your venue’s name or address, any guest’s answers, who picked what, or which venue supplied a count. The Atlas table has no column that could say.
                  </li>
                  <li>
                    <Icon name="shield" />
                    Minimums, enforced in the database: a venue counts with {lim.responses_per_venue} answers; a neighbourhood opens with {lim.venues_in_cell} such venues; an item is listed with {lim.responses_per_item} answers from at least {lim.venues_per_item} venues and only if no one venue
                    supplied more than {percent(lim.max_share_of_one_venue)} of them.
                  </li>
                  <li>
                    <Icon name="check" />
                    You can leave at any time. Your counts leave at the next rebuild, which is queued at once. A guest who removes their answers disappears at the next rebuild too (every six hours).
                  </li>
                  <li>
                    <Icon name="info" />
                    The counts are what guests chose to answer at the venues that joined, a self-selected sample, not the neighbourhood.
                  </li>
                </ul>
              </div>
            </details>
            {canWrite ? (
              <>
                <label className="check">
                  <input type="checkbox" checked={agree} onChange={(e) => setAgree(e.target.checked)} data-testid="atlas-agree" />
                  <span>I understand what is shared and I want this venue to join.</span>
                </label>
                <div className="row row--wrap">
                  <button className="btn btn--primary" type="button" disabled={!agree || busy} onClick={() => change(true)} data-testid="atlas-join">
                    Join the Atlas
                  </button>
                </div>
              </>
            ) : (
              <p className="meta">Only someone who can change the account can join.</p>
            )}
          </div>
        ) : null}
        {doc.opted_in && canWrite ? (
          <div className="row row--wrap">
            <button className="btn btn--ghost" type="button" disabled={busy} onClick={() => change(false)} data-testid="atlas-leave">
              Leave the Atlas
            </button>
          </div>
        ) : null}
      </section>

      {doc.state === "ready" ? <Groups doc={doc} example={false} /> : null}

      {doc.state !== "ready" && doc.state !== "no_location" ? (
        <section className="stack" aria-labelledby="h-example">
          <h2 id="h-example" className="gr-h">
            What it looks like
          </h2>
          <div className="row row--wrap">
            <button className="btn" type="button" aria-expanded={example} onClick={() => setExample((v) => !v)} data-testid="atlas-example-toggle">
              {example ? "Hide the example" : "See an example (invented data)"}
            </button>
          </div>
          {example ? <Groups doc={EXAMPLE} example /> : null}
        </section>
      ) : null}

      <ul className="snd-notes" data-testid="notes">
        <li className="meta">Counts are measured: what guests answered at participating venues, never a headcount and never the whole neighbourhood.</li>
        <li className="meta">Item names come from Qloo’s catalogue. Whether Qloo’s terms allow showing them in a view shared between venues is not confirmed with Qloo.</li>
        <li className="meta">Nothing here says what people in the neighbourhood would like; it says what these guests picked.</li>
      </ul>
    </>
  );
}
