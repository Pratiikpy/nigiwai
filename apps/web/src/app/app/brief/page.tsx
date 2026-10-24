"use client";

import { BriefWorkspace } from "@/components/owner/BriefWorkspace";
import { Loading, Notice, PageHead } from "@/components/owner/ui";
import { useVenue } from "@/lib/venue";

export default function BriefPage() {
  const { venue, tenantPath, canWrite } = useVenue();
  const businessId = venue?.business?.id;
  if (!venue) return <Loading />;
  if (!businessId) {
    return (
      <>
        <PageHead title="Booking Brief" />
        <Notice tone="warn">Set up your venue first.</Notice>
      </>
    );
  }
  return <BriefWorkspace base={`${tenantPath}/businesses/${businessId}`} canWrite={canWrite} />;
}
