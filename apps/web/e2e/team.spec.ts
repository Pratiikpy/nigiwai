import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page } from "@playwright/test";
import { keepRecoveryCode, PASSWORD, resetRateLimits, setTheme, shot, signUp, sql, uniqueEmail, watch } from "./helpers";

test.beforeEach(async () => resetRateLimits());

const WEB = process.env.NIGIWAI_WEB_URL ?? "http://127.0.0.1:3000";
const prefetch = /requestfailed: GET \S+[?&]_rsc=\S+ net::ERR_ABORTED/;

async function a11y(page: Page, label: string) {
  const result = await new AxeBuilder({ page }).analyze();
  expect(result.violations.map((v) => `${label}: ${v.id} ${v.nodes.map((n) => n.html.slice(0, 120)).join(" | ")}`)).toEqual([]);
}

/** Another person: their own browser with its own cookies, the same size of screen as the first. */
async function person(page: Page) {
  const context = await page.context().browser()!.newContext({ baseURL: WEB, viewport: page.viewportSize() ?? undefined });
  const mine = await context.newPage();
  return { context, page: mine, problems: watch(mine) };
}

/** The API builds links from its public address (`localhost` here); the test browser runs on the address of the stack under test. */
const local = (link: string) => {
  const u = new URL(link);
  return `${WEB}${u.pathname}${u.hash}`;
};

/** On a phone the side menu is closed until it is asked for; on a desktop there is no button. */
async function openMenu(page: Page) {
  await page.locator("main.shell__main").waitFor(); // the app has loaded: before that there is no Menu button to find
  const menu = page.getByRole("button", { name: "Menu" });
  if (await menu.isVisible()) await menu.click();
}

/** Make a link as the owner on the Team page and return it as the owner would copy it. */
async function makeLink(page: Page, role: "viewer" | "manager"): Promise<string> {
  await page.getByTestId("team-invite-role").selectOption(role);
  await page.getByTestId("team-invite-create").click();
  const link = await page.getByTestId("team-link").inputValue();
  expect(link).toMatch(/\/invite#[A-Za-z0-9_-]{20,}$/);
  await page.getByRole("button", { name: "Done" }).click();
  await expect(page.getByTestId("team-link")).toHaveCount(0);
  return local(link);
}

test("team: an owner invites a viewer by link, the person joins, a role change and a removal take effect at once, and a used link says so", async ({ page }, info) => {
  test.setTimeout(300_000);
  const problems = watch(page);
  await page.context().grantPermissions(["clipboard-read", "clipboard-write"]);
  const account = `The Lantern ${Date.now().toString(36)}`;
  const { email: ownerEmail } = await signUp(page, account);

  await page.goto("/app/team");
  await expect(page.getByRole("heading", { name: "Team", level: 1 })).toBeVisible();
  const members = page.getByTestId("team-member");
  await expect(members).toHaveCount(1);
  await expect(members.first()).toContainText(ownerEmail);
  await expect(members.first()).toContainText("You");
  // an account always keeps an owner: the only owner cannot step down, and the page says why
  await page.getByTestId("team-role").selectOption("viewer");
  await expect(page.locator('.banner[data-tone="error"]')).toContainText("at least one owner");
  await expect(page.getByTestId("team-role")).toHaveValue("owner");
  await expect(page.getByTestId("team-no-links")).toBeVisible();

  // the link: shown once, copyable, never listed afterwards
  await page.getByTestId("team-invite-role").selectOption("viewer");
  await page.getByTestId("team-invite-create").click();
  const shown = await page.getByTestId("team-link").inputValue();
  expect(shown).toMatch(/^https?:\/\/[^/]+\/invite#[A-Za-z0-9_-]{20,}$/);
  const link = local(shown);
  await expect(page.getByTestId("team-new-link")).toContainText("only time it is shown");
  await page.getByTestId("team-copy").click();
  await expect(page.getByRole("status").filter({ hasText: "Copied." })).toBeVisible();
  expect(await page.evaluate(() => navigator.clipboard.readText())).toBe(shown);
  await shot(page, info, "team-link");
  await a11y(page, "team with a new link");
  await setTheme(page, "dark");
  await shot(page, info, "team-link", "dark");
  await a11y(page, "team with a new link dark");
  await setTheme(page, "light");
  await page.getByRole("button", { name: "Done" }).click();
  await expect(page.getByTestId("team-link")).toHaveCount(0);
  await expect(page.getByTestId("team-open-invite")).toHaveCount(1);
  await expect(page.getByTestId("team-open-invite")).not.toContainText(link.split("#")[1]!);

  // the person opens the link in their own browser
  const guest = await person(page);
  const g = guest.page;
  const guestEmail = uniqueEmail("guest");
  await g.goto(link);
  await expect(g.getByTestId("invite-account")).toHaveText(`Join ${account}`);
  await expect(g.getByTestId("invite-open")).toContainText("As a viewer");
  await expect(g.getByTestId("invite-open")).toContainText("change nothing");
  await shot(g, info, "team-invite");
  await a11y(g, "invite page");
  await setTheme(g, "dark");
  await shot(g, info, "team-invite", "dark");
  await a11y(g, "invite page dark");
  await setTheme(g, "light");
  // a wrong password length is refused with the server's own wording and the link stays usable
  await g.getByLabel("Email").fill(guestEmail);
  await g.getByLabel("Choose a password").fill("short");
  await g.getByTestId("invite-submit").click();
  await expect(g.locator('.banner[data-tone="error"]')).toBeVisible();
  await g.getByLabel("Choose a password").fill(PASSWORD);
  await g.getByTestId("invite-submit").click();
  await keepRecoveryCode(g); // a new login is shown its recovery code once, here too
  await expect(g).toHaveURL(/\/app$/);
  await expect(g.locator(".side__who")).toContainText(account);
  await expect(g.locator(".side__who")).toContainText("viewer");

  // what a viewer sees: the people, with no way to change them
  await g.goto("/app/team");
  await expect(g.getByTestId("team-member")).toHaveCount(2);
  await expect(g.getByTestId("team-role")).toHaveCount(0);
  await expect(g.getByTestId("team-invite-create")).toHaveCount(0);
  await expect(g.getByTestId("team-role-text").first()).toBeVisible();
  await expect(g.getByText("Only an owner can invite people")).toBeVisible();
  await shot(g, info, "team-viewer");
  await a11y(g, "team as a viewer");

  // and the server holds the line: a viewer cannot change the account
  const me = (await (await guest.context.request.get("/api/v1/auth/me")).json()) as { csrf_token: string; tenants: { id: string }[] };
  const tenantId = me.tenants[0]!.id;
  const write = () => guest.context.request.post(`/api/v1/tenants/${tenantId}/businesses`, { headers: { "x-csrf-token": me.csrf_token }, data: { name: "Side room", type: "bar", currency: "GBP" } });
  expect((await write()).status()).toBe(403);

  // the owner sees the new member and promotes them; it takes effect at once
  await page.reload();
  await expect(members).toHaveCount(2);
  const row = members.filter({ hasText: guestEmail });
  await expect(row).toHaveAttribute("data-role", "viewer");
  await row.getByTestId("team-role").selectOption("manager");
  await expect(row).toHaveAttribute("data-role", "manager");
  expect((await write()).status()).toBe(201);
  await g.reload();
  await expect(g.locator(".side__who")).toContainText("manager");

  // the link worked once: a third person gets a plain refusal, not a way in
  const stranger = await person(page);
  await stranger.page.goto(link);
  await expect(stranger.page.getByTestId("invite-dead")).toContainText("already used");
  await expect(stranger.page.getByTestId("invite-submit")).toHaveCount(0);
  await shot(stranger.page, info, "team-invite-used");
  await a11y(stranger.page, "invite used");

  // removing someone ends their access at once, and they are told where they stand
  await row.getByTestId("team-remove").click();
  await row.getByTestId("team-remove-yes").click();
  await expect(members).toHaveCount(1);
  expect([403, 404]).toContain((await guest.context.request.get(`/api/v1/tenants/${tenantId}/team`)).status());
  await g.goto("/app");
  await expect(g.getByTestId("no-account")).toContainText("You are not in an account");
  await shot(g, info, "team-removed");
  await a11y(g, "no account");

  // the one refusal the test provokes on purpose (the only owner stepping down) shows in the console as a 409
  expect(problems.filter((p) => !prefetch.test(p) && !/409 \(Conflict\).*\/team\/members\//.test(p))).toEqual([]);
  expect(guest.problems.filter((p) => !prefetch.test(p) && !/40[134]|Failed to load resource/.test(p))).toEqual([]);
  await guest.context.close();
  await stranger.context.close();
});

test("team: a withdrawn link and an expired link are refused with their own words, and so are broken ones", async ({ page }, info) => {
  test.setTimeout(240_000);
  const problems = watch(page);
  const account = `The Anchor ${Date.now().toString(36)}`;
  await signUp(page, account);
  await page.goto("/app/team");
  const withdrawn = await makeLink(page, "manager");
  await expect(page.getByTestId("team-open-invite")).toHaveCount(1);
  await page.getByTestId("team-revoke").click();
  await expect(page.getByTestId("team-no-links")).toBeVisible();
  const expired = await makeLink(page, "viewer");
  await sql(
    "UPDATE invitation SET expires_at = now() - interval '1 second', created_at = now() - interval '1 day' WHERE tenant_id = (SELECT id FROM tenant WHERE name = $1) AND revoked_at IS NULL",
    [account],
  );

  const visitor = await person(page);
  const v = visitor.page;
  await v.goto(withdrawn);
  await expect(v.getByTestId("invite-dead")).toContainText("This invitation was withdrawn.");
  await v.goto(expired);
  await expect(v.getByTestId("invite-dead")).toContainText("This invitation has expired.");
  await v.goto("/invite");
  await expect(v.getByTestId("invite-dead")).toContainText("This link is incomplete.");
  await v.goto("/invite#short");
  await expect(v.getByTestId("invite-dead")).toContainText("This link is incomplete.");
  await v.goto(`/invite#${"x".repeat(43)}`);
  await expect(v.getByTestId("invite-dead")).toContainText("This invitation link is not valid.");
  await shot(v, info, "team-invite-invalid");
  await a11y(v, "invite invalid");
  expect(problems.filter((p) => !prefetch.test(p))).toEqual([]);
  expect(visitor.problems.filter((p) => !prefetch.test(p) && !/404|422|Failed to load resource/.test(p))).toEqual([]);
  await visitor.context.close();
});

test("team: someone who already has an account joins another with it, and switches between the two", async ({ page }, info) => {
  test.setTimeout(240_000);
  const problems = watch(page);
  const account = `The Lantern ${Date.now().toString(36)}`;
  await signUp(page, account);
  await page.goto("/app/team");
  const link = await makeLink(page, "viewer");

  const other = await person(page);
  const o = other.page;
  const own = `Side Bar ${Date.now().toString(36)}`;
  const { email } = await signUp(o, own);
  await o.goto(link);
  await expect(o.getByTestId("invite-open")).toContainText(`You are signed in as ${email}`);
  await shot(o, info, "team-invite-signed-in");
  await a11y(o, "invite signed in");
  await o.getByTestId("invite-join").click();
  await expect(o).toHaveURL(/\/app$/);

  // two accounts now: a switcher appears, and the one just joined is open
  await openMenu(o);
  const switcher = o.locator("#account-switch");
  await expect(switcher).toHaveCount(1);
  await expect(switcher.locator("option")).toHaveCount(2);
  await expect(switcher).toHaveValue(await switcher.locator("option", { hasText: account }).getAttribute("value") as string);
  await expect(o.locator(".side__who")).toContainText("viewer");
  await shot(o, info, "team-switcher");

  // switching opens the other account, and the browser remembers the choice
  await switcher.selectOption({ label: own });
  await expect(o.locator(".side__who")).toContainText("owner");
  await o.goto("/app/team");
  await expect(o.getByTestId("team-invite-create")).toBeVisible(); // an owner here, not a viewer
  await o.reload();
  await openMenu(o);
  await expect(o.locator("#account-switch option:checked")).toHaveText(own);
  await a11y(o, "switcher");

  // the same link cannot be used a second time by the same person
  await o.goto(link);
  await expect(o.getByTestId("invite-dead")).toContainText("already used");
  expect(problems.filter((p) => !prefetch.test(p))).toEqual([]);
  expect(other.problems.filter((p) => !prefetch.test(p))).toEqual([]);
  await other.context.close();
});
