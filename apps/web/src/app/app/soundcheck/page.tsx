"use client";

import { SoundcheckWorkspace } from "@/components/owner/SoundcheckWorkspace";
import { Loading, Notice, PageHead } from "@/components/owner/ui";
import { useVenue } from "@/lib/venue";

export default function SoundcheckPage() {
  const { venue, tenantPath, canWrite } = useVenue();
  const businessId = venue?.business?.id;
  if (!venue) return <Loading />;
  if (!businessId) {
    return (
      <>
        <PageHead title="Soundcheck" />
        <Notice tone="warn">Set up your venue first, then come back to check an act.</Notice>
      </>
    );
  }
  return <SoundcheckWorkspace base={`${tenantPath}/businesses/${businessId}`} canWrite={canWrite} />;
}
