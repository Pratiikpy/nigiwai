"use client";

import { useRouter } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";
import { Icon } from "@/components/Icon";
import { Loading, Notice, PageHead } from "@/components/owner/ui";
import { ApiError, api, type Me } from "@/lib/api";
import { useSession } from "@/lib/session";
import { type Invitation, type MadeInvitation, type Member, type OfferedRole, type Role, ROLE_CAN, ROLE_NAME, type TeamDoc, day } from "@/lib/team";

const message = (e: unknown, fallback: string) => (e instanceof ApiError ? e.detail : fallback);

function MemberRow({
  member,
  isOwner,
  onRole,
  onRemove,
  busy,
}: {
  member: Member;
  isOwner: boolean;
  onRole: (role: Role) => void;
  onRemove: () => void;
  busy: boolean;
}) {
  const [confirming, setConfirming] = useState(false);
  return (
    <li className="tm-row" data-testid="team-member" data-email={member.email} data-role={member.role}>
      <div className="tm-who">
        <strong>{member.email}</strong>
        <span className="meta">
          {member.you ? "You · " : ""}
          joined {day(member.joined_at)}
        </span>
      </div>
      {isOwner ? (
        <div className="tm-acts">
          <label className="sr-only" htmlFor={`role-${member.user_id}`}>
            Role of {member.email}
          </label>
          <select className="input tm-select" id={`role-${member.user_id}`} data-testid="team-role" value={member.role} disabled={busy} onChange={(e) => onRole(e.target.value as Role)}>
            {(["owner", "manager", "viewer"] as const).map((r) => (
              <option key={r} value={r}>
                {ROLE_NAME[r]}
              </option>
            ))}
          </select>
          {confirming ? (
            <span className="tm-confirm" role="group" aria-label={`Remove ${member.email}?`}>
              <button className="btn btn--sm" type="button" data-testid="team-remove-yes" disabled={busy} onClick={onRemove}>
                {member.you ? "Yes, leave" : "Yes, remove"}
              </button>
              <button className="btn btn--sm btn--ghost" type="button" onClick={() => setConfirming(false)}>
                Keep
              </button>
            </span>
          ) : (
            <button className="btn btn--sm btn--ghost" type="button" data-testid="team-remove" disabled={busy} onClick={() => setConfirming(true)}>
              <Icon name="trash" size="sm" />
              {member.you ? "Leave" : "Remove"}
            </button>
          )}
        </div>
      ) : (
        <span className="pill-role" data-testid="team-role-text">
          {ROLE_NAME[member.role]}
        </span>
      )}
    </li>
  );
}

function NewLink({ made, days, onDone }: { made: MadeInvitation; days: number; onDone: () => void }) {
  const field = useRef<HTMLInputElement>(null);
  const [copied, setCopied] = useState<"yes" | "no" | null>(null);
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(made.url);
      setCopied("yes");
    } catch {
      field.current?.select(); // a blocked clipboard: the link is selected so it can be copied by hand
      setCopied("no");
    }
  };
  return (
    <div className="tm-new stack" data-testid="team-new-link">
      <p>
        <strong>The link for a {made.role}.</strong> It works once, for {days} days. This is the only time it is shown, so copy it now and send it to them yourself.
      </p>
      <div className="tm-link">
        <label className="sr-only" htmlFor="tm-link">
          Invitation link
        </label>
        <input ref={field} className="input" id="tm-link" data-testid="team-link" readOnly value={made.url} onFocus={(e) => e.currentTarget.select()} />
        <button className="btn" type="button" data-testid="team-copy" onClick={() => void copy()}>
          <Icon name="copy" />
          Copy
        </button>
      </div>
      <p className="meta" role="status">
        {copied === "yes" ? "Copied." : copied === "no" ? "Your browser would not copy it. The link is selected: press Ctrl+C." : " "}
      </p>
      <button className="btn btn--sm tm-done" type="button" onClick={onDone}>
        Done
      </button>
    </div>
  );
}

export function TeamWorkspace({ base, isOwner }: { base: string; isOwner: boolean }) {
  const router = useRouter();
  const { adopt } = useSession();
  const [doc, setDoc] = useState<TeamDoc | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [role, setRole] = useState<OfferedRole>("viewer");
  const [made, setMade] = useState<MadeInvitation | null>(null);

  const load = useCallback(() => api<TeamDoc>(`${base}/team`).then(setDoc), [base]);

  useEffect(() => {
    let live = true;
    api<TeamDoc>(`${base}/team`)
      .then((d) => live && setDoc(d))
      .catch((e: unknown) => live && setProblem(message(e, "We couldn’t load the team.")));
    return () => {
      live = false;
    };
  }, [base]);

  const run = async (work: () => Promise<void>, failed: string) => {
    setProblem(null);
    setBusy(true);
    try {
      await work();
    } catch (e) {
      setProblem(message(e, failed));
    } finally {
      setBusy(false);
    }
  };

  if (!doc && !problem) return <Loading />;
  if (!doc) return <Notice tone="error">{problem}</Notice>;

  const create = () =>
    run(async () => {
      setMade(await api<MadeInvitation>(`${base}/team/invitations`, { method: "POST", body: { role } }));
      await load();
    }, "We couldn’t make the link.");

  const withdraw = (i: Invitation) =>
    run(async () => {
      await api<void>(`${base}/team/invitations/${i.id}`, { method: "DELETE" });
      await load();
    }, "We couldn’t withdraw that link.");

  const changeRole = (m: Member, next: Role) =>
    run(async () => {
      setDoc(await api<TeamDoc>(`${base}/team/members/${m.user_id}`, { method: "PUT", body: { role: next } }));
    }, "We couldn’t change that role.");

  const remove = (m: Member) =>
    run(async () => {
      await api<void>(`${base}/team/members/${m.user_id}`, { method: "DELETE" });
      if (m.you) {
        adopt(await api<Me>("/auth/me")); // they left this account: the app opens whichever one they still have
        router.replace("/app");
        return;
      }
      await load();
    }, "We couldn’t remove that person.");

  return (
    <>
      <PageHead title="Team" lead="Who is in this account and what each person can do. Anyone who joins sees the same venue, and what they may change depends on their role." />
      {problem ? <Notice tone="error">{problem}</Notice> : null}

      <section className="card stack" aria-labelledby="h-people">
        <h2 id="h-people" className="card__title">
          People
        </h2>
        <ul className="tm-list" data-testid="team-members">
          {doc.members.map((m) => (
            <MemberRow key={m.user_id} member={m} isOwner={isOwner} busy={busy} onRole={(r) => void changeRole(m, r)} onRemove={() => void remove(m)} />
          ))}
        </ul>
        <dl className="tm-roles">
          {(["owner", "manager", "viewer"] as const).map((r) => (
            <div key={r}>
              <dt>{ROLE_NAME[r]}</dt>
              <dd>{ROLE_CAN[r]}</dd>
            </div>
          ))}
        </dl>
        {isOwner ? <p className="meta">An account always keeps at least one owner.</p> : <p className="meta">Only an owner can invite people, change a role or remove someone.</p>}
      </section>

      {isOwner ? (
        <section className="card stack" aria-labelledby="h-invite">
          <h2 id="h-invite" className="card__title">
            Invite someone
          </h2>
          <p className="muted">
            You get a link to send them yourself, by message or in person. It works once and expires after {doc.limits.invite_days} days. Nothing is emailed from here.
          </p>
          {made ? (
            <NewLink made={made} days={doc.limits.invite_days} onDone={() => setMade(null)} />
          ) : (
            <div className="tm-make">
              <div className="field">
                <label htmlFor="tm-role">They join as</label>
                <select className="input" id="tm-role" data-testid="team-invite-role" value={role} onChange={(e) => setRole(e.target.value as OfferedRole)}>
                  <option value="viewer">Viewer</option>
                  <option value="manager">Manager</option>
                </select>
                <p className="field__hint">{ROLE_CAN[role]}</p>
              </div>
              <button className="btn btn--primary" type="button" data-testid="team-invite-create" disabled={busy} onClick={() => void create()}>
                <Icon name="plus" />
                Make an invitation link
              </button>
            </div>
          )}

          <h3 className="tm-sub">Open links</h3>
          {doc.invitations.length === 0 ? (
            <p className="meta" data-testid="team-no-links">
              No links are open.
            </p>
          ) : (
            <ul className="tm-list" data-testid="team-open-links">
              {doc.invitations.map((i) => (
                <li key={i.id} className="tm-row" data-testid="team-open-invite" data-role={i.role}>
                  <div className="tm-who">
                    <strong>{ROLE_NAME[i.role]} link</strong>
                    <span className="meta">
                      made {day(i.created_at)} · expires {day(i.expires_at)}
                    </span>
                  </div>
                  <button className="btn btn--sm btn--ghost" type="button" data-testid="team-revoke" disabled={busy} onClick={() => void withdraw(i)}>
                    Withdraw
                  </button>
                </li>
              ))}
            </ul>
          )}
          <p className="meta">A link cannot be shown again after it is made. If you lose one, withdraw it and make another.</p>
        </section>
      ) : null}
    </>
  );
}
