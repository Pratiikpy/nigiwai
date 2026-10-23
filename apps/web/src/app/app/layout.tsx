import type { Metadata } from "next";
import { Shell } from "@/components/owner/Shell";
import { SessionProvider } from "@/lib/session";

export const metadata: Metadata = { title: "Your venue", robots: { index: false, follow: false } };

export default function OwnerLayout({ children }: { children: React.ReactNode }) {
  return (
    <SessionProvider>
      <Shell>{children}</Shell>
    </SessionProvider>
  );
}
