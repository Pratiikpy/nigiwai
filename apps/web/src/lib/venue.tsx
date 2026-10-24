"use client";

import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import { ApiError, api, type Business, type Location, type QrPoint, type Stats, type Survey } from "./api";
import type { Plan } from "./onboarding";
import { useSession } from "./session";

export type Venue = {
  business: Business | null;
  location: Location | null;
  qrPoints: QrPoint[];
  survey: Survey | null;
  stats: Stats | null;
  /** The dashboard plan the owner confirmed in onboarding, or null if they have not been through it. */
  plan: Plan | null;
};

type Ctx = {
  /** `null` until the first load finishes. */
  venue: Venue | null;
  error: string | null;
  reload: () => Promise<void>;
  tenantPath: string;
  canWrite: boolean;
};

const VenueCtx = createContext<Ctx | null>(null);

async function loadVenue(tp: string): Promise<Venue> {
  const businesses = await api<Business[]>(`${tp}/businesses`);
  const business = businesses[0] ?? null;
  if (!business) return { business: null, location: null, qrPoints: [], survey: null, stats: null, plan: null };
  const [locations, survey, stats, plan] = await Promise.all([
    api<Location[]>(`${tp}/businesses/${business.id}/locations`),
    api<Survey | null>(`${tp}/businesses/${business.id}/survey`),
    api<Stats>(`${tp}/businesses/${business.id}/stats`),
    api<Plan | null>(`${tp}/plan`),
  ]);
  const location = locations[0] ?? null;
  const qrPoints = location ? await api<QrPoint[]>(`${tp}/locations/${location.id}/qr-points`) : [];
  return { business, location, qrPoints, survey, stats, plan };
}

/** The signed-in owner's one business, its first location, QR points, survey and counts, loaded together. */
export function VenueProvider({ children }: { children: React.ReactNode }) {
  const { state } = useSession();
  const tenant = state.status === "ready" ? state.tenant : null;
  const [venue, setVenue] = useState<Venue | null>(null);
  const [error, setError] = useState<string | null>(null);
  const tenantPath = tenant ? `/tenants/${tenant.id}` : "";

  const reload = useCallback(async () => {
    if (!tenantPath) return;
    try {
      setVenue(await loadVenue(tenantPath));
      setError(null);
    } catch (e) {
      setError(e instanceof ApiError ? e.detail : "We couldn't load your venue.");
    }
  }, [tenantPath]);

  useEffect(() => {
    let live = true;
    if (!tenantPath) return;
    loadVenue(tenantPath)
      .then((v) => live && (setVenue(v), setError(null)))
      .catch((e: unknown) => live && setError(e instanceof ApiError ? e.detail : "We couldn't load your venue."));
    return () => {
      live = false;
    };
  }, [tenantPath]);

  const value = useMemo<Ctx>(
    () => ({ venue, error, reload, tenantPath, canWrite: tenant?.role !== "viewer" }),
    [venue, error, reload, tenantPath, tenant?.role],
  );
  return <VenueCtx.Provider value={value}>{children}</VenueCtx.Provider>;
}

export function useVenue(): Ctx {
  const value = useContext(VenueCtx);
  if (!value) throw new Error("useVenue must be used inside VenueProvider");
  return value;
}
