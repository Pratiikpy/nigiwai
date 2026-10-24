import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page } from "@playwright/test";
import { openAllWeek, plantCrowd, plantLineup, plantSuggestions, publishedVenue, resetRateLimits, setRhythm, setTheme, shot, signIn, sql, watch } from "./helpers";

test.beforeEach(async () => resetRateLimits());

async function a11y(page: Page, label: string) {
  const result = await new AxeBuilder({ page }).analyze();
  expect(result.violations.map((v) => `${label}: ${v.id} ${v.nodes.map((n) => n.html.slice(0, 120)).join(" | ")}`)).toEqual([]);
}
const prefetch = /requestfailed: GET \S+[?&]_rsc=\S+ net::ERR_ABORTED/;
const GAP = /\[[^\]\n]{1,80}\]/g;

test("drafts: made from an accepted action, never approvable with a gap, every step logged, and nothing is sent", async ({ page, request }, info) => {
  test.setTimeout(180_000);
  const problems = watch(page);
  const venue = await publishedVenue(request);
  await plantCrowd(venue.businessId, venue.qrId, 90);
  await setRhythm(venue.qrId);
  await openAllWeek(venue.businessId);
  await plantLineup(venue.tenantId, venue.businessId, { events: 40 });
  await plantSuggestions(venue.tenantId, venue.businessId, [
    { name: "Velvet Harbour", score: 88, best: "Indie rock acts" },
    { name: "The Quiet Engines", score: 81, best: "Jazz acts" },
  ]);
  await signIn(page, venue.email);

  // nothing can be drafted from an action until it is accepted
  await page.goto("/app/drafts");
  await expect(page.getByRole("heading", { name: "Drafts", level: 1 })).toBeVisible();
  await expect(page.getByTestId("empty")).toBeVisible();
  await expect(page.getByText("Accept an action on Today and you can prepare")).toBeVisible();
  await shot(page, info, "drafts-empty");
  await a11y(page, "drafts empty");

  await page.goto("/app/today");
  const fill = page.getByTestId("action").nth(0);
  await expect(fill).toBeVisible();
  await expect(fill.getByRole("link", { name: "Prepare drafts" })).toHaveCount(0); // not before it is accepted
  await fill.getByRole("button", { name: "Accept" }).click();
  await expect(fill).toHaveAttribute("data-state", "accepted");
  await fill.getByRole("link", { name: "Prepare drafts" }).click();
  await expect(page).toHaveURL(/\/app\/drafts\?action=/);
  await expect(page.getByTestId("make").locator('li[data-wanted="true"]')).toContainText("Velvet Harbour");
  await page.getByRole("button", { name: "Prepare these three" }).click();

  const drafts = page.getByTestId("draft");
  await expect(drafts).toHaveCount(3);
  const outreach = page.locator('[data-testid="draft"][data-kind="outreach"]');
  await expect(outreach.getByRole("heading")).toContainText("Booking enquiry: Velvet Harbour at The Lantern");
  await expect(outreach.getByTestId("status")).toHaveText("Draft");
  await expect(outreach.getByTestId("gaps")).toContainText("3 gaps to fill");
  await expect(outreach.getByTestId("approve")).toBeDisabled();
  await expect(outreach.getByLabel("Text")).toHaveValue(/Wednesday 14:00 to 17:00/);
  await shot(page, info, "drafts-made");
  await a11y(page, "drafts made");

  // fill the gaps in, save, approve
  const text = outreach.getByLabel("Text");
  const original = await text.inputValue();
  await text.fill(original.replace(GAP, "Sam"));
  await expect(outreach.getByText("You have unsaved changes")).toBeVisible();
  await expect(outreach.getByTestId("approve")).toBeDisabled(); // approval is of the saved text
  await outreach.getByTestId("save").click();
  await expect(outreach.getByTestId("gaps")).toHaveText("No gaps left.");
  await expect(outreach.getByTestId("approve")).toBeEnabled();
  await outreach.getByTestId("approve").click();
  await expect(outreach.getByTestId("status")).toHaveText("Approved");
  await expect(outreach).toContainText("Nigiwai has sent, posted and booked nothing");
  await expect(outreach.getByTestId("mailto")).toHaveAttribute("href", /^mailto:\?subject=Booking%20enquiry/);
  await expect(outreach.getByRole("button", { name: "Copy text" })).toBeVisible();
  await shot(page, info, "drafts-approved");
  await a11y(page, "drafts approved");
  await setTheme(page, "dark");
  await shot(page, info, "drafts-approved", "dark");
  await a11y(page, "drafts approved dark");
  await setTheme(page, "light");

  // changing the words takes the approval back
  await text.fill(`${await text.inputValue()}\nP.S. We can host a sound check at 17:00.`);
  await outreach.getByTestId("save").click();
  await expect(outreach.getByTestId("status")).toHaveText("Draft");
  await expect(outreach.getByTestId("mailto")).toHaveCount(0);

  // the event page and the post still hold their gaps
  const page_ = page.locator('[data-testid="draft"][data-kind="event_page"]');
  await expect(page_.getByTestId("gaps")).toContainText("gaps to fill");
  await expect(page_.getByTestId("approve")).toBeDisabled();

  // an ad angle from one group
  await page.getByRole("button", { name: "Draft an ad angle" }).first().click();
  const ad = page.locator('[data-testid="draft"][data-kind="ad_copy"]');
  await expect(ad).toHaveCount(1);
  await expect(ad.getByLabel("Text")).toHaveValue(/Headline \(\d+ of 40 characters\)/);
  await expect(ad.getByLabel("Text")).toHaveValue(/Primary text \(\d+ of 125 characters\)/);

  // withdraw one: it moves out of the way, and cannot be edited
  await page_.getByRole("button", { name: "Withdraw" }).click();
  await expect(page.locator('[data-testid="draft"][data-kind="event_page"]')).toHaveCount(1);
  await page.getByText(/Withdrawn \(1\)/).click();
  const gone = page.locator('[data-testid="draft"][data-status="withdrawn"]');
  await expect(gone).toHaveCount(1);
  await expect(gone.getByLabel("Text")).toBeDisabled();
  // delete asks first
  await gone.getByRole("button", { name: "Delete", exact: true }).click();
  await gone.getByRole("button", { name: "Keep it" }).click();
  await expect(gone).toHaveCount(1);
  await gone.getByRole("button", { name: "Delete", exact: true }).click();
  await gone.getByRole("button", { name: "Delete it" }).click();
  await expect(page.locator('[data-testid="draft"][data-status="withdrawn"]')).toHaveCount(0);

  // every step is in the audit log, and nothing was sent anywhere
  const log = await sql<{ action: string; n: number }>("SELECT action, count(*)::int AS n FROM audit_log WHERE action LIKE 'draft.%' AND tenant_id = $1 GROUP BY action", [venue.tenantId]);
  const counts = Object.fromEntries(log.rows.map((r) => [r.action, r.n]));
  expect(counts).toMatchObject({ "draft.create": 4, "draft.approve": 1, "draft.withdraw": 1, "draft.delete": 1 });
  expect(counts["draft.edit"]).toBeGreaterThanOrEqual(2);
  expect(problems.filter((p) => !prefetch.test(p) && !/409/.test(p))).toEqual([]);
});
