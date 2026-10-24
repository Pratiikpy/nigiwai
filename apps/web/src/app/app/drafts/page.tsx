"use client";

import { DraftsWorkspace } from "@/components/owner/DraftsWorkspace";
import { Loading, Notice, PageHead } from "@/components/owner/ui";
import { useVenue } from "@/lib/venue";

export default function DraftsPage() {
  const { venue, tenantPath, canWrite } = useVenue();
  const businessId = venue?.business?.id;
  if (!venue) return <Loading />;
  if (!businessId) {
    return (
      <>
        <PageHead title="Drafts" />
        <Notice tone="warn">Set up your venue first, then prepare drafts.</Notice>
      </>
    );
  }
  return <DraftsWorkspace base={`${tenantPath}/businesses/${businessId}`} canWrite={canWrite} />;
}
