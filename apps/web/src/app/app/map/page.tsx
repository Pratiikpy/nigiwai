"use client";

import { MapWorkspace } from "@/components/owner/MapWorkspace";
import { Loading, Notice, PageHead } from "@/components/owner/ui";
import { useVenue } from "@/lib/venue";

export default function MapPage() {
  const { venue, tenantPath } = useVenue();
  const businessId = venue?.business?.id;
  if (!venue) return <Loading />;
  if (!businessId) {
    return (
      <>
        <PageHead title="Crowd map" />
        <Notice tone="warn">Set up your venue first, then your crowd will appear here.</Notice>
      </>
    );
  }
  return <MapWorkspace base={`${tenantPath}/businesses/${businessId}`} />;
}
