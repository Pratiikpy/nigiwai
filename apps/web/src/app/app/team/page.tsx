"use client";

import { Loading } from "@/components/owner/ui";
import { TeamWorkspace } from "@/components/owner/TeamWorkspace";
import { useSession } from "@/lib/session";

export default function TeamPage() {
  const { state } = useSession();
  if (state.status !== "ready") return <Loading />;
  return <TeamWorkspace base={`/tenants/${state.tenant.id}`} isOwner={state.tenant.role === "owner"} />;
}
