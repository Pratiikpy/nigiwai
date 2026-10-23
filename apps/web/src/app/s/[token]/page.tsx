import type { Metadata } from "next";
import { SurveyApp } from "@/components/survey/SurveyApp";

// The QR token is a credential: keep this page out of search indexes and out of referrers.
export const metadata: Metadata = {
  title: "Tell us what you love",
  robots: { index: false, follow: false },
  referrer: "no-referrer",
};

export default async function SurveyPage({ params }: { params: Promise<{ token: string }> }) {
  const { token } = await params;
  return <SurveyApp token={token} />;
}
