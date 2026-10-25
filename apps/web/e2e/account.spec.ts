import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page } from "@playwright/test";
import { keepRecoveryCode, PASSWORD, resetRateLimits, setTheme, shot, signIn, signUp, sql, uniqueEmail, watch } from "./helpers";

test.beforeEach(async () => resetRateLimits());

const WEB = process.env.NIGIWAI_WEB_URL ?? "http://127.0.0.1:3000";
const NEW = "another-long-passphrase-7";
const THIRD = "a-third-long-passphrase-3";
const CODE = /^([A-Z2-9]{5}-){3}[A-Z2-9]{5}$/;
// the one refusal each test provokes on purpose shows in the console as a failed request
const deliberate = /Failed to load resource: the server responded with a status of (401|403|409|422)/;
const prefetch = /requestfailed: GET \S+[?&]_rsc=\S+ net::ERR_ABORTED/;

async function a11y(page: Page, label: string) {
  const result = await new AxeBuilder({ page }).analyze();
  expect(result.violations.map((v) => `${label}: ${v.id} ${v.nodes.map((n) => n.html.slice(0, 120)).join(" | ")}`)).toEqual([]);
}

async function person(page: Page) {
  const context = await page.context().browser()!.newContext({ baseURL: WEB, viewport: page.viewportSize() ?? undefined });
  const mine = await context.newPage();
  return { context, page: mine, problems: watch(mine) };
}

async function openMenu(page: Page) {
  await page.locator("main.shell__main").waitFor(); // the app has loaded: before that there is no Menu button to find
  const menu = page.getByRole("button", { name: "Menu" });
  if (await menu.isVisible()) await menu.click();
}

async function forgot(page: Page, email: string, code: string, password: string) {
  await page.goto("/forgot");
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Recovery code").fill(code);
  await page.getByLabel("New password").fill(password);
  await page.getByTestId("forgot-submit").click();
}

test("account: signing up shows the recovery code once, and it is the way back in after a forgotten password", async ({ page }, info) => {
  test.setTimeout(240_000);
  const problems = watch(page);
  await page.context().grantPermissions(["clipboard-read", "clipboard-write"]);
  const email = uniqueEmail("owner");

  await page.goto("/signup");
  await page.getByLabel("Venue or business name").fill("The Lantern");
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password", { exact: true }).fill(PASSWORD);
  await page.getByRole("button", { name: "Create account" }).click();

  // the step: the code, a way to keep it, and no way on until the person says they have
  const shown = page.getByTestId("recovery-code");
  await expect(shown).toBeVisible();
  const code = (await shown.innerText()).trim();
  expect(code).toMatch(CODE);
  await expect(page.getByTestId("recovery")).toContainText("does not email password resets");
  await expect(page.getByTestId("recovery-continue")).toBeDisabled();
  await page.getByTestId("recovery-copy").click();
  await expect(page.getByRole("status").filter({ hasText: "Copied." })).toBeVisible();
  expect(await page.evaluate(() => navigator.clipboard.readText())).toBe(code);
  const [download] = await Promise.all([page.waitForEvent("download"), page.getByTestId("recovery-download").click()]);
  expect(download.suggestedFilename()).toBe("nigiwai-recovery-code.txt");
  const saved = await (await import("node:fs/promises")).readFile((await download.path())!, "utf8");
  expect(saved).toContain(code);
  expect(saved).toContain(email);
  await shot(page, info, "account-recovery");
  await a11y(page, "recovery step");
  await setTheme(page, "dark");
  await shot(page, info, "account-recovery", "dark");
  await a11y(page, "recovery step dark");
  await setTheme(page, "light");
  await page.getByTestId("recovery-saved").check();
  await expect(page.getByTestId("recovery-continue")).toBeEnabled();
  await page.getByTestId("recovery-continue").click();
  await expect(page).toHaveURL(/\/app$/);

  // another browser is signed in too; then the password is forgotten
  const other = await person(page);
  await signIn(other.page, email);
  await openMenu(page);
  await page.getByRole("button", { name: "Sign out" }).click();
  await expect(page).toHaveURL(/\/login$/);
  await page.getByTestId("forgot-link").click();
  await expect(page).toHaveURL(/\/forgot$/);
  await expect(page.getByRole("heading", { name: "Forgot your password?" })).toBeVisible();
  await shot(page, info, "account-forgot");
  await a11y(page, "forgot");

  // a wrong code, a weak password: each refused plainly, and the real code is not used up
  await forgot(page, email, "AAAAA-BBBBB-CCCCC-DDDDD", NEW);
  await expect(page.locator('.banner[data-tone="error"]')).toContainText("do not match");
  await forgot(page, email, code, "short");
  await expect(page.locator('.banner[data-tone="error"]')).toContainText("at least 10");
  // the right code, typed the way a person copies it: lower case, spaces for dashes
  await forgot(page, email, code.toLowerCase().replaceAll("-", " "), NEW);
  const fresh = (await page.getByTestId("recovery-code").innerText()).trim();
  expect(fresh).toMatch(CODE);
  expect(fresh).not.toBe(code);
  await expect(page.getByRole("heading", { name: "Your password is changed" })).toBeVisible();
  await a11y(page, "forgot done");
  await page.getByTestId("recovery-saved").check();
  await page.getByTestId("recovery-continue").click();
  await expect(page).toHaveURL(/\/login$/);

  // the old password and the used code are dead; the new password works; the other browser was signed out
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password", { exact: true }).fill(PASSWORD);
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.locator('.banner[data-tone="error"]')).toContainText("wrong");
  await page.getByLabel("Password", { exact: true }).fill(NEW);
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page).toHaveURL(/\/app$/);
  await forgot(page, email, code, THIRD);
  await expect(page.locator('.banner[data-tone="error"]')).toContainText("do not match");
  await other.page.goto("/app");
  await expect(other.page).toHaveURL(/\/login$/);

  expect(problems.filter((p) => !deliberate.test(p) && !prefetch.test(p))).toEqual([]);
  expect(other.problems.filter((p) => !deliberate.test(p) && !prefetch.test(p))).toEqual([]);
  await other.context.close();
});

test("account: changing the password, making a new recovery code and signing out everywhere", async ({ page }, info) => {
  test.setTimeout(240_000);
  const problems = watch(page);
  const { email, recoveryCode } = await signUp(page, "The Lantern");
  const phone = await person(page);
  await signIn(phone.page, email);

  await page.goto("/app/account");
  await expect(page.getByRole("heading", { name: "Your login", level: 1 })).toBeVisible();
  await expect(page.getByTestId("rc-status")).toContainText("A recovery code was made on");
  await shot(page, info, "account-page");
  await a11y(page, "account page");
  await setTheme(page, "dark");
  await shot(page, info, "account-page", "dark");
  await a11y(page, "account page dark");
  await setTheme(page, "light");

  // change password: the old one is asked for, a weak one is refused, the other device is signed out and this one stays
  await page.getByLabel("Current password").fill("not-my-password-at-all");
  await page.getByLabel("New password").fill(NEW);
  await page.getByTestId("pw-submit").click();
  await expect(page.locator('.banner[data-tone="error"]')).toContainText("not right");
  await page.getByLabel("Current password").fill(PASSWORD);
  await page.getByLabel("New password").fill("short");
  await page.getByTestId("pw-submit").click();
  await expect(page.locator('.banner[data-tone="error"]')).toContainText("at least 10");
  await page.getByLabel("New password").fill(NEW);
  await page.getByTestId("pw-submit").click();
  await expect(page.getByText("Your password is changed. Every other device was signed out.")).toBeVisible();
  await page.reload();
  await expect(page.getByRole("heading", { name: "Your login", level: 1 })).toBeVisible();
  await phone.page.goto("/app");
  await expect(phone.page).toHaveURL(/\/login$/);

  // a new recovery code needs the password and cancels the old one
  await page.locator("#rc-password").fill(NEW);
  await page.getByTestId("rc-make").click();
  const fresh = (await page.getByTestId("recovery-code").innerText()).trim();
  expect(fresh).toMatch(CODE);
  expect(fresh).not.toBe(recoveryCode);
  await shot(page, info, "account-new-code");
  await a11y(page, "new recovery code");
  await page.getByTestId("recovery-saved").check();
  await page.getByTestId("recovery-continue").click();
  await expect(page.getByTestId("rc-status")).toContainText("A recovery code was made on");
  const old = await sql<{ n: number }>("SELECT count(*)::int AS n FROM app_user WHERE email = $1 AND recovery_hash = sha256($2::bytea)", [email, Buffer.from(recoveryCode.replaceAll("-", ""))]);
  expect(old.rows[0]?.n).toBe(0); // the first code is no longer the stored one

  // sign out everywhere ends this sign-in too
  await page.getByTestId("sign-out-everywhere").click();
  await expect(page).toHaveURL(/\/login$/);
  await page.goto("/app");
  await expect(page).toHaveURL(/\/login$/);
  expect(problems.filter((p) => !deliberate.test(p) && !prefetch.test(p))).toEqual([]);
  await phone.context.close();
});

test("account: deleting an account removes everything in it, and the login can then be deleted too", async ({ page }, info) => {
  test.setTimeout(240_000);
  const problems = watch(page);
  const name = `Delete Me ${Date.now().toString(36)}`;
  const { email } = await signUp(page, name);
  // some data of its own: a venue, then a survey
  await page.goto("/app/venue");
  await page.getByLabel("Name", { exact: true }).fill(name);
  await page.getByLabel("Type").selectOption("live_music_venue");
  await page.getByLabel("Currency").fill("gbp");
  await page.getByLabel("Latitude").fill("51.5072");
  await page.getByLabel("Longitude").fill("-0.1276");
  await page.getByLabel("Time zone").fill("Europe/London");
  await page.getByRole("button", { name: "Fri" }).click();
  await page.getByRole("button", { name: "Save", exact: true }).click();
  await expect(page.getByText("Saved.")).toBeVisible();
  const tenant = (await sql<{ id: string }>("SELECT id FROM tenant WHERE name = $1", [name])).rows[0]?.id;
  expect(tenant).toBeTruthy();
  expect(((await sql<{ n: number }>("SELECT count(*)::int AS n FROM business WHERE tenant_id = $1", [tenant])).rows[0]?.n ?? 0)).toBeGreaterThan(0);

  await page.goto("/app/account");
  // the login cannot go while it alone holds up the account, and the page says which
  await page.getByTestId("delete-login").locator("summary").click();
  await page.getByTestId("delete-login").getByLabel("Your password").fill(PASSWORD);
  await page.getByTestId("delete-login-go").click();
  await expect(page.getByTestId("delete-login-problem")).toContainText(`only owner of “${name}”`);

  // the account: the name and the password are both asked for
  const del = page.getByTestId("delete-account");
  await del.locator("summary").click();
  await expect(del).toContainText("cannot be undone");
  await shot(page, info, "account-delete");
  await a11y(page, "delete account");
  await setTheme(page, "dark");
  await shot(page, info, "account-delete", "dark");
  await a11y(page, "delete account dark");
  await setTheme(page, "light");
  await del.getByTestId("delete-name").fill("Something else");
  await del.getByLabel("Your password").fill(PASSWORD);
  await del.getByTestId("delete-account-go").click();
  await expect(del.locator('.banner[data-tone="error"]')).toContainText("does not match");
  await del.getByTestId("delete-name").fill(name);
  await del.getByLabel("Your password").fill("not-my-password-at-all");
  await del.getByTestId("delete-account-go").click();
  await expect(del.locator('.banner[data-tone="error"]')).toContainText("not right");
  expect(((await sql<{ n: number }>("SELECT count(*)::int AS n FROM tenant WHERE id = $1", [tenant])).rows[0]?.n ?? 0)).toBe(1);
  await del.getByLabel("Your password").fill(PASSWORD);
  await del.getByTestId("delete-account-go").click();

  // gone: the account and every row of it, and the person is told they are in none
  await expect(page.getByTestId("no-account")).toBeVisible();
  const left = await sql<{ t: string; n: number }>(
    "SELECT t, n FROM (SELECT 'tenant' AS t, count(*)::int AS n FROM tenant WHERE id = $1 UNION ALL SELECT 'business', count(*)::int FROM business WHERE tenant_id = $1 UNION ALL SELECT 'membership', count(*)::int FROM membership WHERE tenant_id = $1 UNION ALL SELECT 'audit', count(*)::int FROM audit_log WHERE tenant_id = $1) x WHERE n > 0",
    [tenant],
  );
  expect(left.rows).toEqual([]);
  await shot(page, info, "account-none");
  await a11y(page, "no account after deleting");

  // and the login, from the page a person with no account sees
  await page.getByTestId("delete-login").locator("summary").click();
  await page.getByTestId("delete-login").getByLabel("Your password").fill(PASSWORD);
  await page.getByTestId("delete-login-go").click();
  await expect(page).toHaveURL(/\/login$/);
  expect(((await sql<{ n: number }>("SELECT count(*)::int AS n FROM app_user WHERE email = $1", [email])).rows[0]?.n ?? 0)).toBe(0);
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password", { exact: true }).fill(PASSWORD);
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.locator('.banner[data-tone="error"]')).toContainText("wrong");
  expect(problems.filter((p) => !deliberate.test(p) && !prefetch.test(p))).toEqual([]);
});

test("account: a viewer is offered no way to delete the account, and can leave by deleting their login", async ({ page }, info) => {
  test.setTimeout(240_000);
  const account = `The Anchor ${Date.now().toString(36)}`;
  const { email: ownerEmail } = await signUp(page, account);
  await page.goto("/app/team");
  await page.getByTestId("team-invite-role").selectOption("viewer");
  await page.getByTestId("team-invite-create").click();
  const link = await page.getByTestId("team-link").inputValue();
  const guest = await person(page);
  const g = guest.page;
  const guestEmail = uniqueEmail("guest");
  await g.goto(`${WEB}${new URL(link).pathname}${new URL(link).hash}`);
  await g.getByLabel("Email").fill(guestEmail);
  await g.getByLabel("Choose a password").fill(PASSWORD);
  await g.getByTestId("invite-submit").click();
  await keepRecoveryCode(g);
  await expect(g).toHaveURL(/\/app$/);
  await g.goto("/app/account");
  await expect(g.getByTestId("account-row")).toHaveCount(1);
  await expect(g.getByTestId("account-row")).toContainText("Viewer");
  await expect(g.getByTestId("delete-account")).toHaveCount(0);
  await shot(g, info, "account-viewer");
  await a11y(g, "account as a viewer");
  await g.getByTestId("delete-login").locator("summary").click();
  await g.getByTestId("delete-login").getByLabel("Your password").fill(PASSWORD);
  await g.getByTestId("delete-login-go").click();
  await expect(g).toHaveURL(/\/login$/);
  // the account carries on without them
  await page.goto("/app/team");
  await expect(page.getByTestId("team-member")).toHaveCount(1);
  await expect(page.getByTestId("team-member").first()).toContainText(ownerEmail);
  await guest.context.close();
});

test("account: a person left in no account can start a venue of their own, and start another from their login page", async ({ page }, info) => {
  test.setTimeout(240_000);
  const problems = watch(page);
  const first = `Gone Soon ${Date.now().toString(36)}`;
  await signUp(page, first);
  await page.goto("/app/account");
  const del = page.getByTestId("delete-account");
  await del.locator("summary").click();
  await del.getByTestId("delete-name").fill(first);
  await del.getByLabel("Your password").fill(PASSWORD);
  await del.getByTestId("delete-account-go").click();

  // nothing left: the page says so and offers a way forward that is not a dead end
  await expect(page.getByTestId("no-account")).toBeVisible();
  const again = page.getByTestId("new-account");
  await expect(again).toBeVisible();
  await shot(page, info, "account-none-start");
  await a11y(page, "no account, start a venue");
  await expect(again.getByTestId("new-account-go")).toBeDisabled(); // no name yet
  const second = `Fresh Start ${Date.now().toString(36)}`;
  await again.getByLabel("Venue or business name").fill(second);
  await again.getByTestId("new-account-go").click();
  await expect(page).toHaveURL(/\/app$/);
  await expect(page.getByRole("heading", { name: second, level: 1 })).toBeVisible();
  await expect(page.locator(".side__who")).toContainText("owner");

  // and a second venue beside it, from the login page; the menu then offers both
  await page.goto("/app/account");
  const third = `Side Room ${Date.now().toString(36)}`;
  await page.getByTestId("new-account").getByLabel("Venue or business name").fill(third);
  await page.getByTestId("new-account-go").click();
  await expect(page).toHaveURL(/\/app$/);
  await expect(page.getByRole("heading", { name: third, level: 1 })).toBeVisible();
  await openMenu(page);
  const switcher = page.locator("#account-switch");
  await expect(switcher.locator("option")).toHaveCount(2);
  await shot(page, info, "account-two-venues");
  await a11y(page, "two venues");
  const names = await switcher.locator("option").allInnerTexts();
  expect(names.sort()).toEqual([second, third].sort());
  expect(problems.filter((p) => !deliberate.test(p) && !prefetch.test(p))).toEqual([]);
});

test("account: an owner downloads a copy of the account's data, and a viewer is not offered it", async ({ page }, info) => {
  test.setTimeout(240_000);
  const problems = watch(page);
  const name = `Copy Me ${Date.now().toString(36)}`;
  await signUp(page, name);
  await page.goto("/app/account");
  const box = page.getByTestId("export-account");
  await expect(box).toContainText("no guest on their own");
  await shot(page, info, "account-export");
  await a11y(page, "account export");
  // The link is a real download: clicking it starts one for this address. (This machine's Chrome cancels every download it is handed, even a
  // plain PDF from a trivial server, so the saved file is read with the same session through the request context instead.)
  const href = (await page.getByTestId("export-link").getAttribute("href"))!;
  const [download] = await Promise.all([page.waitForEvent("download"), page.getByTestId("export-link").click()]);
  expect(download.url()).toContain(href);
  const res = await page.request.get(href);
  expect(res.status()).toBe(200);
  expect(res.headers()["content-disposition"]).toMatch(/^attachment; filename="nigiwai-export-\d{8}-\d{4}\.zip"$/);
  const bytes = await res.body();
  expect(bytes.subarray(0, 2).toString()).toBe("PK"); // a ZIP
  expect(bytes.length).toBeGreaterThan(500);
  expect((await sql<{ n: number }>("SELECT count(*)::int AS n FROM audit_log WHERE action = 'account.export' AND tenant_id = (SELECT id FROM tenant WHERE name = $1)", [name])).rows[0]?.n).toBeGreaterThanOrEqual(1);
  expect(problems.filter((p) => !deliberate.test(p) && !prefetch.test(p))).toEqual([]);
});
