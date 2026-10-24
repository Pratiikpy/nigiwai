"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { RecoveryCode } from "@/components/auth/RecoveryCode";
import { Icon } from "@/components/Icon";
import { Loading, Notice, PageHead } from "@/components/owner/ui";
import { ApiError, api, setCsrf, type Me } from "@/lib/api";
import type { AccountDoc, AccountRow } from "@/lib/account";
import { rememberAccount, useSession } from "@/lib/session";
import { ROLE_NAME } from "@/lib/team";

const message = (e: unknown, fallback: string) => (e instanceof ApiError ? e.detail : fallback);
const day = (iso: string) => new Date(iso).toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" });

/** Asks for the password again, and says what went wrong in the server's own words. */
function useAction() {
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  const run = async (work: () => Promise<void>, fallback: string) => {
    setBusy(true);
    setProblem(null);
    try {
      await work();
    } catch (e) {
      setProblem(message(e, fallback));
    } finally {
      setBusy(false);
    }
  };
  return { busy, problem, run, clear: () => setProblem(null) };
}

function PasswordField({ id, label, value, onChange, autoComplete }: { id: string; label: string; value: string; onChange: (v: string) => void; autoComplete: string }) {
  return (
    <div className="field">
      <label htmlFor={id}>{label}</label>
      <input className="input" id={id} type="password" autoComplete={autoComplete} maxLength={200} value={value} onChange={(e) => onChange(e.target.value)} />
    </div>
  );
}

function ChangePassword() {
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [done, setDone] = useState(false);
  const { busy, problem, run } = useAction();
  const submit = (event: React.FormEvent) => {
    event.preventDefault();
    setDone(false);
    void run(async () => {
      await api<void>("/account/password", { method: "PUT", body: { current_password: current, new_password: next } });
      setCurrent("");
      setNext("");
      setDone(true);
    }, "We couldn’t change the password.");
  };
  return (
    <section className="card stack" aria-labelledby="h-pw">
      <h2 id="h-pw" className="card__title">
        Change your password
      </h2>
      <form className="stack" onSubmit={submit} noValidate>
        <PasswordField id="pw-current" label="Current password" value={current} onChange={setCurrent} autoComplete="current-password" />
        <PasswordField id="pw-new" label="New password" value={next} onChange={setNext} autoComplete="new-password" />
        <p className="meta">At least 10 characters. Every other device is signed out when this changes.</p>
        {problem ? <Notice tone="error">{problem}</Notice> : null}
        {done ? <Notice tone="ok">Your password is changed. Every other device was signed out.</Notice> : null}
        <button className="btn btn--fit" type="submit" data-testid="pw-submit" disabled={busy || !current || !next}>
          Change password
        </button>
      </form>
    </section>
  );
}

function Recovery({ doc, onMade }: { doc: AccountDoc; onMade: () => void }) {
  const [password, setPassword] = useState("");
  const [code, setCode] = useState<string | null>(null);
  const { busy, problem, run } = useAction();
  const make = (event: React.FormEvent) => {
    event.preventDefault();
    void run(async () => {
      const made = await api<{ recovery_code: string }>("/account/recovery-code", { method: "POST", body: { password } });
      setCode(made.recovery_code);
      setPassword("");
    }, "We couldn’t make a new code.");
  };
  return (
    <section className="card stack" aria-labelledby="h-rc">
      <h2 id="h-rc" className="card__title">
        Recovery code
      </h2>
      {code ? (
        <RecoveryCode
          code={code}
          email={doc.email}
          heading="Your new recovery code"
          level="h3"
          doneLabel="Done"
          onDone={() => {
            setCode(null);
            onMade();
          }}
        />
      ) : (
        <>
          <p data-testid="rc-status">
            {doc.recovery_set_at ? `A recovery code was made on ${day(doc.recovery_set_at)}.` : "You have no recovery code yet, so a forgotten password could not be recovered."}
          </p>
          <p className="muted">There is no emailed reset: the code is how you get back in if you forget your password. Making a new one cancels the old one.</p>
          <form className="stack" onSubmit={make} noValidate>
            <PasswordField id="rc-password" label="Your password" value={password} onChange={setPassword} autoComplete="current-password" />
            {problem ? <Notice tone="error">{problem}</Notice> : null}
            <button className="btn btn--fit" type="submit" data-testid="rc-make" disabled={busy || !password}>
              Make a new recovery code
            </button>
          </form>
        </>
      )}
    </section>
  );
}

function DeleteAccount({ row, onDeleted }: { row: AccountRow; onDeleted: () => Promise<void> }) {
  const [name, setName] = useState("");
  const [password, setPassword] = useState("");
  const { busy, problem, run } = useAction();
  const submit = (event: React.FormEvent) => {
    event.preventDefault();
    void run(async () => {
      await api<void>(`/tenants/${row.id}/delete-account`, { method: "POST", body: { confirm_name: name, password } });
      await onDeleted();
    }, "We couldn’t delete the account.");
  };
  const others = row.others ?? 0;
  return (
    <details className="disc" data-testid="delete-account">
      <summary>
        <Icon name="chev-r" />
        Delete this account and all its data
      </summary>
      <form className="disc__body stack" onSubmit={submit} noValidate>
        <p>
          This deletes <strong>{row.name}</strong> for good: its venue, survey, posters, every guest answer, your groups, plans, drafts, moves and the record of changes.
          {others > 0 ? ` ${others === 1 ? "One other person is" : `${others} other people are`} in it and will lose access (they keep their own logins).` : ""} If it had joined the City Taste
          Atlas, its counts leave the pooled table at once. It cannot be undone and nothing is kept.
        </p>
        <div className="field">
          <label htmlFor={`del-name-${row.id}`}>Type the account name to confirm</label>
          <input className="input" id={`del-name-${row.id}`} data-testid="delete-name" autoComplete="off" value={name} onChange={(e) => setName(e.target.value)} />
        </div>
        <PasswordField id={`del-pw-${row.id}`} label="Your password" value={password} onChange={setPassword} autoComplete="current-password" />
        {problem ? <Notice tone="error">{problem}</Notice> : null}
        <button className="btn btn--danger btn--fit" type="submit" data-testid="delete-account-go" disabled={busy || !name || !password}>
          <Icon name="trash" />
          Delete this account for good
        </button>
      </form>
    </details>
  );
}

/** Start another venue from this login. Used on the login page and on the page a person sees when they are in no account. */
export function NewAccount({ lead }: { lead: string }) {
  const router = useRouter();
  const { adopt } = useSession();
  const [name, setName] = useState("");
  const { busy, problem, run } = useAction();
  const submit = (event: React.FormEvent) => {
    event.preventDefault();
    void run(async () => {
      const made = await api<{ id: string }>("/account/accounts", { method: "POST", body: { business_name: name } });
      rememberAccount(made.id);
      adopt(await api<Me>("/auth/me"));
      router.replace("/app");
    }, "We couldn’t start that venue.");
  };
  return (
    <form className="stack" onSubmit={submit} noValidate data-testid="new-account">
      <p className="muted">{lead}</p>
      <div className="field">
        <label htmlFor="na-name">Venue or business name</label>
        <input className="input" id="na-name" maxLength={120} autoComplete="off" value={name} onChange={(e) => setName(e.target.value)} />
      </div>
      {problem ? <Notice tone="error">{problem}</Notice> : null}
      <button className="btn btn--primary btn--fit" type="submit" data-testid="new-account-go" disabled={busy || !name.trim()}>
        <Icon name="plus" />
        Start this venue
      </button>
    </form>
  );
}

/** Delete the person: their sign-in and their place in every account. Used here and on the page shown to someone in no account. */
export function DeleteLogin({ onDeleted }: { onDeleted: () => void }) {
  const [password, setPassword] = useState("");
  const { busy, problem, run } = useAction();
  const submit = (event: React.FormEvent) => {
    event.preventDefault();
    void run(async () => {
      await api<void>("/account/delete", { method: "POST", body: { password } });
      onDeleted();
    }, "We couldn’t delete your login.");
  };
  return (
    <details className="disc" data-testid="delete-login">
      <summary>
        <Icon name="chev-r" />
        Delete my login
      </summary>
      <form className="disc__body stack" onSubmit={submit} noValidate>
        <p>
          This deletes your sign-in and takes you out of every account you are in. The accounts and what you made in them stay with the people who are still there. You cannot delete your
          login while you are the only owner of an account: make someone else an owner, or delete the account, first.
        </p>
        <PasswordField id="dl-password" label="Your password" value={password} onChange={setPassword} autoComplete="current-password" />
        {problem ? (
          <Notice tone="error">
            <span data-testid="delete-login-problem">{problem}</span>
          </Notice>
        ) : null}
        <button className="btn btn--danger btn--fit" type="submit" data-testid="delete-login-go" disabled={busy || !password}>
          <Icon name="trash" />
          Delete my login for good
        </button>
      </form>
    </details>
  );
}

export function AccountWorkspace() {
  const router = useRouter();
  const { adopt } = useSession();
  const [doc, setDoc] = useState<AccountDoc | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  const [version, setVersion] = useState(0);
  const out = useAction();

  useEffect(() => {
    let live = true;
    api<AccountDoc>("/account")
      .then((d) => live && setDoc(d))
      .catch((e: unknown) => live && setProblem(message(e, "We couldn’t load your login.")));
    return () => {
      live = false;
    };
  }, [version]);

  if (!doc && !problem) return <Loading />;
  if (!doc) return <Notice tone="error">{problem}</Notice>;

  const afterAccountDeleted = async () => {
    adopt(await api<Me>("/auth/me")); // the person's accounts without the one just deleted
    router.replace("/app");
  };

  return (
    <>
      <PageHead title="Your login" lead={`Signed in as ${doc.email}, since ${day(doc.created_at)}.`} />
      <ChangePassword />
      <Recovery doc={doc} onMade={() => setVersion((v) => v + 1)} />

      <section className="card stack" aria-labelledby="h-out">
        <h2 id="h-out" className="card__title">
          Signed in on other devices
        </h2>
        <p className="muted">Sign out everywhere ends every sign-in, this one included.</p>
        {out.problem ? <Notice tone="error">{out.problem}</Notice> : null}
        <button
          className="btn btn--fit"
          type="button"
          data-testid="sign-out-everywhere"
          disabled={out.busy}
          onClick={() =>
            void out.run(async () => {
              await api<void>("/account/sign-out-everywhere", { method: "POST" });
              setCsrf(null);
              router.replace("/login");
            }, "We couldn’t sign you out.")
          }
        >
          Sign out everywhere
        </button>
      </section>

      <section className="card stack" aria-labelledby="h-acc">
        <h2 id="h-acc" className="card__title">
          Accounts you are in
        </h2>
        <ul className="tm-list" data-testid="account-list">
          {doc.accounts.map((a) => (
            <li key={a.id} className="tm-row" data-testid="account-row" data-role={a.role}>
              <div className="tm-who">
                <strong>{a.name}</strong>
                <span className="meta">{ROLE_NAME[a.role]}</span>
              </div>
              {a.role === "owner" ? <DeleteAccount row={a} onDeleted={afterAccountDeleted} /> : null}
            </li>
          ))}
        </ul>
        <h3 className="tm-sub">Start another venue</h3>
        <NewAccount lead="A second venue or business, with its own survey, posters and people. You switch between your accounts from the menu." />
        <DeleteLogin
          onDeleted={() => {
            setCsrf(null);
            router.replace("/login");
          }}
        />
      </section>
    </>
  );
}
