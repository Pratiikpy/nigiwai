"use client";

import { MovesWorkspace } from "@/components/owner/MovesWorkspace";
import { Loading, Notice, PageHead } from "@/components/owner/ui";
import { useVenue } from "@/lib/venue";

export default function MovesPage() {
  const { venue, tenantPath, canWrite } = useVenue();
  const businessId = venue?.business?.id;
  if (!venue) return <Loading />;
  if (!businessId) {
    return (
      <>
        <PageHead title="Moves" />
        <Notice tone="warn">Set up your venue first, then log what you change.</Notice>
      </>
    );
  }
  return <MovesWorkspace base={`${tenantPath}/businesses/${businessId}`} canWrite={canWrite} />;
}
