import type { Metadata } from "next";
import { PublicShell } from "@/components/PublicShell";
import "../../design/trace.css";
import "../../design/v06.css";

export const metadata: Metadata = {
  title: { default: "Nigiwai", template: "%s · Nigiwai" },
  description: "Read the crowd you already have, then check an act against it before you book.",
};

export default function PublicLayout({ children }: { children: React.ReactNode }) {
  return <PublicShell>{children}</PublicShell>;
}
