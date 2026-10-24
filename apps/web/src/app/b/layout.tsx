import type { Metadata } from "next";
import "../../design/trace.css";
import "../../design/v06.css";

// A shared brief is reachable by its link alone: keep it out of search indexes and out of referrers.
export const metadata: Metadata = {
  title: "Booking Brief",
  robots: { index: false, follow: false },
  referrer: "no-referrer",
};

export default function SharedBriefLayout({ children }: { children: React.ReactNode }) {
  return <main className="pubmain">{children}</main>;
}
