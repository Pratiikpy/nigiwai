import type { Metadata } from "next";
import { Suspense } from "react";
import { Loading } from "@/components/owner/ui";
import { isRequested } from "@/lib/demo";
import { TryVenue } from "./TryVenue";

export async function generateMetadata({ params }: { params: Promise<{ slug: string }> }): Promise<Metadata> {
  const { slug } = await params;
  return {
    title: "Demo venue",
    description: "A real venue read from its public lineups: soundcheck any act, see the crowd map and the booking brief.",
    // A venue someone asked for is theirs to share by address; it is not for search engines, and it is deleted after a week.
    robots: isRequested(slug) ? { index: false, follow: false } : undefined,
  };
}

export default async function TryVenuePage({ params }: { params: Promise<{ slug: string }> }) {
  const { slug } = await params;
  return (
    <Suspense fallback={<Loading label="Opening the venue…" />}>
      <TryVenue slug={slug} />
    </Suspense>
  );
}
