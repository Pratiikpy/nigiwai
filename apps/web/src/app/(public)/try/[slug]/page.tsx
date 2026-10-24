import type { Metadata } from "next";
import { Suspense } from "react";
import { Loading } from "@/components/owner/ui";
import { TryVenue } from "./TryVenue";

export const metadata: Metadata = {
  title: "Demo venue",
  description: "A real venue read from its public lineups: soundcheck any act, see the crowd map and the booking brief.",
};

export default async function TryVenuePage({ params }: { params: Promise<{ slug: string }> }) {
  const { slug } = await params;
  return (
    <Suspense fallback={<Loading label="Opening the venue…" />}>
      <TryVenue slug={slug} />
    </Suspense>
  );
}
