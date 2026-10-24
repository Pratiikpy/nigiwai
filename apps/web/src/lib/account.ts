/** Types and wording for the login: the account page, the recovery code and the forgotten-password page. */

export type AccountRow = { id: string; name: string; role: "owner" | "manager" | "viewer"; sole_owner: boolean; others: number | null };
export type AccountDoc = { email: string; created_at: string; recovery_set_at: string | null; accounts: AccountRow[] };

/** The file a person can keep: the code, what it is for and which login it belongs to. */
export function recoveryFile(email: string, code: string): string {
  return [
    "Nigiwai recovery code",
    "",
    `Login: ${email}`,
    `Code:  ${code}`,
    "",
    "If you forget your password, open the Forgot password page, enter your email and this code, and choose a new password.",
    "The code works once. A new one is shown each time it is used. Keep this file somewhere private.",
    "",
  ].join("\n");
}
