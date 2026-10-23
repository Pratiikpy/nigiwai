"use client";

import { useRouter } from "next/navigation";
import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import { ApiError, api, setCsrf, type Me, type Tenant } from "./api";

type SessionState =
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "ready"; me: Me; tenant: Tenant };

type Session = {
  state: SessionState;
  signOut: () => Promise<void>;
  /** Replace the signed-in user's details after signing in or up. */
  adopt: (me: Me) => void;
};

const Ctx = createContext<Session | null>(null);

/** Loads the signed-in owner. Anyone who is not signed in is sent to the sign-in page. */
export function SessionProvider({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const [state, setState] = useState<SessionState>({ status: "loading" });

  const adopt = useCallback((me: Me) => {
    setCsrf(me.csrf_token);
    const tenant = me.tenants[0];
    if (!tenant) setState({ status: "error", message: "This account has no venue." });
    else setState({ status: "ready", me, tenant });
  }, []);

  useEffect(() => {
    let live = true;
    api<Me>("/auth/me")
      .then((me) => live && adopt(me))
      .catch((error: unknown) => {
        if (!live) return;
        if (error instanceof ApiError && error.status === 401) router.replace("/login");
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

  const value = useMemo(() => ({ state, signOut, adopt }), [state, signOut, adopt]);
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
