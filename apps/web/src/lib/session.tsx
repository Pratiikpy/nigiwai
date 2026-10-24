"use client";

import { useRouter } from "next/navigation";
import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import { ApiError, api, setCsrf, setSessionEndedHandler, type Me, type Tenant } from "./api";

type SessionState =
  | { status: "loading" }
  | { status: "error"; message: string }
  /** Signed in, but not in any account (for example after being removed from the only one). */
  | { status: "none"; me: Me }
  | { status: "ready"; me: Me; tenant: Tenant };

const CHOICE_KEY = "nigiwai.account";

/** The account this browser last worked in. A convenience only: when it is missing or stale the first account is used. */
function remembered(): string | null {
  try {
    return window.localStorage.getItem(CHOICE_KEY);
  } catch {
    return null;
  }
}

/** Remember the account to open next time, for this browser only. */
export function rememberAccount(id: string): void {
  try {
    window.localStorage.setItem(CHOICE_KEY, id);
  } catch {
    /* storage can be blocked: the first account opens instead */
  }
}

type Session = {
  state: SessionState;
  signOut: () => Promise<void>;
  /** Replace the signed-in user's details after signing in or up. */
  adopt: (me: Me) => void;
  /** Work in another account the person belongs to. The whole workspace is rebuilt for it, so nothing from the last account stays on screen. */
  switchAccount: (id: string) => void;
};

const Ctx = createContext<Session | null>(null);

/** Loads the signed-in owner. Anyone who is not signed in is sent to the sign-in page. */
export function SessionProvider({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const [state, setState] = useState<SessionState>({ status: "loading" });

  const adopt = useCallback((me: Me) => {
    setCsrf(me.csrf_token);
    const wanted = remembered();
    const tenant = me.tenants.find((t) => t.id === wanted) ?? me.tenants[0];
    if (!tenant) setState({ status: "none", me });
    else setState({ status: "ready", me, tenant });
  }, []);

  // When the session ends while the owner is working, go to sign in and come back to this page afterwards.
  useEffect(() => {
    setSessionEndedHandler(() => {
      setCsrf(null);
      const here = `${window.location.pathname}${window.location.search}`;
      router.replace(`/login?next=${encodeURIComponent(here)}`);
    });
    return () => setSessionEndedHandler(null);
  }, [router]);

  useEffect(() => {
    let live = true;
    api<Me>("/auth/me")
      .then((me) => live && adopt(me))
      .catch((error: unknown) => {
        if (!live) return;
        if (error instanceof ApiError && error.status === 401) {
          const here = `${window.location.pathname}${window.location.search}`;
          router.replace(here === "/app" ? "/login" : `/login?next=${encodeURIComponent(here)}`);
        }
        else setState({ status: "error", message: error instanceof ApiError ? error.detail : "Something went wrong." });
      });
    return () => {
      live = false;
    };
  }, [adopt, router]);

  const signOut = useCallback(async () => {
    try {
      await api<void>("/auth/logout", { method: "POST" });
    } finally {
      setCsrf(null);
      router.replace("/login");
    }
  }, [router]);

  const switchAccount = useCallback(
    (id: string) => {
      rememberAccount(id);
      setState((s) => {
        if (s.status !== "ready") return s;
        const tenant = s.me.tenants.find((t) => t.id === id);
        return tenant ? { status: "ready", me: s.me, tenant } : s;
      });
      router.push("/app");
    },
    [router],
  );

  const value = useMemo(() => ({ state, signOut, adopt, switchAccount }), [state, signOut, adopt, switchAccount]);
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useSession(): Session {
  const value = useContext(Ctx);
  if (!value) throw new Error("useSession must be used inside SessionProvider");
  return value;
}

/** The tenant path prefix every owner call uses. */
export function useTenantPath(): string {
  const { state } = useSession();
  if (state.status !== "ready") throw new Error("session not ready");
  return `/tenants/${state.tenant.id}`;
}
