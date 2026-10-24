import type { Metadata } from "next";
import { Shell } from "@/components/owner/Shell";
import { SessionProvider } from "@/lib/session";
import "../../design/trace.css";
import "../../design/today.css";
import "../../design/v06.css";

export const metadata: Metadata = { title: "Your venue", robots: { index: false, follow: false } };

export default function OwnerLayout({ children }: { children: React.ReactNode }) {
  return (
    <SessionProvider>
      <Shell>{children}</Shell>
    </SessionProvider>
  );
}
