"use client";

import { GrowWorkspace } from "@/components/owner/GrowWorkspace";
import { Loading, Notice, PageHead } from "@/components/owner/ui";
import { useVenue } from "@/lib/venue";

export default function GrowPage() {
  const { venue, tenantPath, canWrite } = useVenue();
  const businessId = venue?.business?.id;
  if (!venue) return <Loading />;
  if (!businessId) {
    return (
      <>
        <PageHead title="Grow" />
        <Notice tone="warn">Set up your venue first, then come back to see who else might come.</Notice>
      </>
    );
  }
  return <GrowWorkspace base={`${tenantPath}/businesses/${businessId}`} canWrite={canWrite} />;
}
