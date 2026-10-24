"use client";

import { useEffect, useRef, useState } from "react";
import { Icon } from "@/components/Icon";
import { Loading, Notice, PageHead } from "@/components/owner/ui";
import { ApiError, api } from "@/lib/api";
import { DRAFT_LABELS, type Draft, type DraftsDoc, gapsIn } from "@/lib/drafts";

type CardProps = { draft: Draft; base: string; canWrite: boolean; onChanged: () => void; onProblem: (message: string) => void };

function DraftCard({ draft, base, canWrite, onChanged, onProblem }: CardProps) {
  const [subject, setSubject] = useState(draft.subject);
  const [body, setBody] = useState(draft.body);
  const [busy, setBusy] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const [copied, setCopied] = useState(false);
  const url = `${base}/drafts/${draft.id}`;
  const dirty = subject !== draft.subject || body !== draft.body;
  const gaps = gapsIn(body);
  const editable = canWrite && draft.status !== "withdrawn";

  const run = async (work: () => Promise<unknown>) => {
    setBusy(true);
    try {
      await work();
      onChanged();
    } catch (e) {
      onProblem(e instanceof ApiError ? e.detail : "That didn’t work. Please try again.");
    } finally {
      setBusy(false);
    }
  };

  const copy = () => {
    navigator.clipboard
      .writeText(`${draft.subject}\n\n${draft.body}`)
      .then(() => {
        setCopied(true);
        setTimeout(() => setCopied(false), 2500);
      })
      .catch(() => onProblem("Your browser did not allow copying. Select the text and copy it yourself."));
  };

  return (
    <article className="card dr" data-testid="draft" data-kind={draft.kind} data-status={draft.status} aria-labelledby={`dr-${draft.id}`}>
      <header className="dr__head">
        <div>
          <p className="eyebrow">{DRAFT_LABELS[draft.kind]}</p>
          <h3 className="dr__title" id={`dr-${draft.id}`}>
            {draft.subject}
          </h3>
        </div>
        <span className="dr__status" data-status={draft.status} data-testid="status">
          {draft.status === "draft" ? "Draft" : draft.status === "approved" ? "Approved" : "Withdrawn"}
        </span>
      </header>
      <div className="field">
        <label htmlFor={`s-${draft.id}`}>Subject or title</label>
        <input className="input" id={`s-${draft.id}`} maxLength={200} value={subject} onChange={(e) => setSubject(e.target.value)} disabled={!editable || busy} />
      </div>
      <div className="field">
        <label htmlFor={`b-${draft.id}`}>Text</label>
        <textarea
          className="textarea dr__body"
          id={`b-${draft.id}`}
          rows={Math.min(18, Math.max(6, body.split("\n").length + 1))}
          maxLength={4000}
          value={body}
          onChange={(e) => setBody(e.target.value)}
          disabled={!editable || busy}
        />
      </div>
      {draft.status === "draft" ? (
        <p className="dr__gaps" data-testid="gaps">
          {gaps.length ? (
            <>
              <strong>
                {gaps.length} {gaps.length === 1 ? "gap" : "gaps"} to fill:
              </strong>{" "}
              {gaps.join(", ")}
            </>
          ) : (
            "No gaps left."
          )}
        </p>
      ) : null}
      {dirty && draft.status !== "withdrawn" ? <p className="meta">You have unsaved changes. Approval is of the saved text, so save first.</p> : null}
      {draft.status === "approved" ? (
        <Notice tone="ok">
          Approved{draft.decided_at ? ` on ${new Date(draft.decided_at).toLocaleDateString()}` : ""}. Nigiwai has sent, posted and booked nothing; take the text from here.
        </Notice>
      ) : null}
      <div className="row row--wrap">
        {editable ? (
          <button className="btn btn--sm" type="button" disabled={busy || !dirty || !subject.trim() || !body.trim()} onClick={() => void run(() => api(url, { method: "PUT", body: { subject, body } }))} data-testid="save">
            Save changes
          </button>
        ) : null}
        {canWrite && draft.status === "draft" ? (
          <button className="btn btn--sm btn--primary" type="button" disabled={busy || dirty || !draft.can_approve} onClick={() => void run(() => api(`${url}/approve`, { method: "POST" }))} data-testid="approve">
            Approve
          </button>
        ) : null}
        {draft.status === "approved" ? (
          <>
            <button className="btn btn--sm" type="button" onClick={copy}>
              <Icon name="copy" size="sm" />
              {copied ? "Copied" : "Copy text"}
            </button>
            {draft.mailto ? (
              <a className="btn btn--sm" href={draft.mailto} data-testid="mailto">
                <Icon name="send" size="sm" />
                Open in my email
              </a>
            ) : null}
          </>
        ) : null}
        {canWrite && draft.status !== "withdrawn" ? (
          <button className="btn btn--sm btn--ghost" type="button" disabled={busy} onClick={() => void run(() => api(`${url}/withdraw`, { method: "POST" }))}>
            Withdraw
          </button>
        ) : null}
        {canWrite ? (
          confirming ? (
            <>
              <button className="btn btn--sm btn--primary" type="button" disabled={busy} onClick={() => void run(() => api(url, { method: "DELETE" }))}>
                Delete it
              </button>
              <button className="btn btn--sm btn--ghost" type="button" onClick={() => setConfirming(false)}>
                Keep it
              </button>
            </>
          ) : (
            <button className="btn btn--sm btn--ghost" type="button" disabled={busy} onClick={() => setConfirming(true)}>
              Delete
            </button>
          )
        ) : null}
      </div>
      {draft.status === "draft" && !draft.can_approve && !dirty && draft.why_not ? <p className="meta">{draft.why_not}</p> : null}
    </article>
  );
}

export function DraftsWorkspace({ base, canWrite }: { base: string; canWrite: boolean }) {
  const [doc, setDoc] = useState<DraftsDoc | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  const [tick, setTick] = useState(0);
  const [busy, setBusy] = useState(false);
  const [wanted, setWanted] = useState<string | null>(null);
  const read = useRef(false);

  useEffect(() => {
    let live = true;
    api<DraftsDoc>(`${base}/drafts`)
      .then((d) => live && setDoc(d))
      .catch((e: unknown) => live && setProblem(e instanceof ApiError ? e.detail : "We couldn’t load your drafts."));
    return () => {
      live = false;
    };
  }, [base, tick]);

  // a link from Today names the action to draft from
  useEffect(() => {
    if (read.current) return;
    read.current = true;
    const key = new URLSearchParams(window.location.search).get("action");
    // eslint-disable-next-line react-hooks/set-state-in-effect -- reading the address once on arrival
    if (key) setWanted(key);
  }, []);

  if (!doc && !problem) return <Loading />;
  if (!doc) return <Notice tone="error">{problem}</Notice>;

  const make = async (body: Record<string, unknown>) => {
    setBusy(true);
    setProblem(null);
    try {
      await api(`${base}/drafts`, { method: "POST", body });
      setTick((n) => n + 1);
    } catch (e) {
      setProblem(e instanceof ApiError ? e.detail : "That didn’t work. Please try again.");
    } finally {
      setBusy(false);
    }
  };

  const { drafts, sources } = doc;
  const open = drafts.filter((d) => d.status !== "withdrawn");
  const withdrawn = drafts.filter((d) => d.status === "withdrawn");
  const groups = sources.groups.filter((g) => g.loves.length);
  const card = (d: Draft) => <DraftCard key={`${d.id}-${d.edited_at}-${d.status}`} draft={d} base={base} canWrite={canWrite} onChanged={() => setTick((n) => n + 1)} onProblem={setProblem} />;

  return (
    <>
      <PageHead
        title="Drafts"
        lead="Text prepared from your own records for you to read, change and approve. Nigiwai sends, posts and books nothing: approving a draft only marks it as yours, and you take it from there."
      />
      {problem ? <Notice tone="error">{problem}</Notice> : null}

      {canWrite ? (
        <section className="card stack" aria-labelledby="dr-make" data-testid="make">
          <h2 className="card__title" id="dr-make">
            Make drafts
          </h2>
          {sources.actions.length ? (
            <ul className="dr__sources">
              {sources.actions.map((a) => (
                <li key={a.key} data-wanted={wanted === a.key}>
                  <span>
                    <strong>{a.title}</strong>
                    <span className="meta"> An enquiry to the act, an event page and a post.</span>
                  </span>
                  <button className="btn btn--sm btn--primary" type="button" disabled={busy} onClick={() => void make({ from_action: a.key })}>
                    Prepare these three
                  </button>
                </li>
              ))}
            </ul>
          ) : (
            <p className="meta">Accept an action on Today and you can prepare an enquiry, an event page and a post for it here.</p>
          )}
          {groups.length ? (
            <>
              <h3 className="dr__sub">Ad angles</h3>
              <ul className="dr__sources">
                {groups.map((g) => (
                  <li key={g.index}>
                    <span>
                      <strong>{g.label}</strong>
                      <span className="meta"> Picks most: {g.loves.slice(0, 3).join(", ")}</span>
                    </span>
                    <button className="btn btn--sm" type="button" disabled={busy} onClick={() => void make({ group_index: g.index })}>
                      Draft an ad angle
                    </button>
                  </li>
                ))}
              </ul>
            </>
          ) : (
            <p className="meta">Once your guests fall into groups (My people), you can draft an ad angle for each.</p>
          )}
        </section>
      ) : null}

      {open.length === 0 && withdrawn.length === 0 ? (
        <section className="card stack" data-testid="empty">
          <h2 className="card__title">No drafts yet</h2>
          <p>
            Drafts are made from what you have accepted on Today and from what each group of your guests picks. Every gap the product cannot know, such as a date, a fee or a contact, is left as a [bracketed] blank that you must fill before you can approve.
          </p>
        </section>
      ) : null}

      <div className="stack" data-testid="drafts">
        {open.map(card)}
      </div>
      {withdrawn.length ? (
        <details className="disc">
          <summary>
            <Icon name="chev-r" />
            Withdrawn ({withdrawn.length})
          </summary>
          <div className="disc__body stack">{withdrawn.map(card)}</div>
        </details>
      ) : null}
    </>
  );
}
