"use client";

import { SoundWorkspace } from "@/components/owner/SoundWorkspace";
import { Loading, Notice, PageHead } from "@/components/owner/ui";
import { useVenue } from "@/lib/venue";

export default function SoundPage() {
  const { venue, tenantPath, canWrite } = useVenue();
  const businessId = venue?.business?.id;
  if (!venue) return <Loading />;
  if (!businessId) {
    return (
      <>
        <PageHead title="Sound plan" />
        <Notice tone="warn">Set up your venue first, then come back for a plan.</Notice>
      </>
    );
  }
  return <SoundWorkspace base={`${tenantPath}/businesses/${businessId}`} canWrite={canWrite} />;
}
