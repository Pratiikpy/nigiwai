import type { Metadata } from "next";
import { InviteJoin } from "@/components/auth/InviteJoin";

// The secret is in the part of the address after the #, which the browser never sends to us. These keep it off search results and
// out of the Referer header of anything the page links to.
export const metadata: Metadata = { title: "Join a team", robots: { index: false, follow: false }, referrer: "no-referrer" };

export default function InvitePage() {
  return <InviteJoin />;
}
