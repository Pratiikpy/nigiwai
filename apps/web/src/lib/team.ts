/** Types and wording for the Team page and the invitation page, as the API returns them. */

export type Role = "owner" | "manager" | "viewer";
export type OfferedRole = "manager" | "viewer";

export type Member = { user_id: string; email: string; role: Role; joined_at: string; you: boolean };
export type Invitation = { id: string; role: OfferedRole; created_at: string; expires_at: string };
export type TeamDoc = { members: Member[]; invitations: Invitation[]; limits: { invite_days: number; max_open: number } };
/** A new link, as returned once: the secret is in `url` and is never shown again. */
export type MadeInvitation = { id: string; role: OfferedRole; token: string; url: string; expires_at: string };
export type Peek = { account: string; role: OfferedRole; state: "open" | "used" | "revoked" | "expired"; reason: string | null };

export const ROLE_NAME: Record<Role, string> = { owner: "Owner", manager: "Manager", viewer: "Viewer" };

/** What each role can do, in the words the owner sees when choosing one. */
export const ROLE_CAN: Record<Role, string> = {
  owner: "Everything a manager can do, and decides who is in the account.",
  manager: "Sets up and changes the venue, the survey, the plan and the drafts.",
  viewer: "Can look at everything and change nothing.",
};

export function day(iso: string): string {
  return new Date(iso).toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" });
}

/** The secret of an invitation link is whatever follows the `#`. It never reaches a server, so it is never in a log or a referrer. */
export function tokenFromHash(hash: string): string | null {
  const token = hash.replace(/^#/, "");
  return /^[A-Za-z0-9_-]{20,100}$/.test(token) ? token : null;
}
