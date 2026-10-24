"use client";

import { AtlasWorkspace } from "@/components/owner/AtlasWorkspace";
import { Loading, Notice, PageHead } from "@/components/owner/ui";
import { useVenue } from "@/lib/venue";

export default function AtlasPage() {
  const { venue, tenantPath, canWrite } = useVenue();
  const businessId = venue?.business?.id;
  if (!venue) return <Loading />;
  if (!businessId) {
    return (
      <>
        <PageHead title="City Taste Atlas" />
        <Notice tone="warn">Set up your venue first, then come back to see your neighbourhood.</Notice>
      </>
    );
  }
  return <AtlasWorkspace base={`${tenantPath}/businesses/${businessId}`} canWrite={canWrite} />;
}
