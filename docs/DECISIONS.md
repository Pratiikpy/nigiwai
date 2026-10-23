# Decisions

Every non-trivial decision: what, why, the alternatives and why they lost, and the evidence. Newest last. Evidence marked VERIFIED was checked against the real tool or API on the date shown.

## D1. Licence: MIT (2026-10-23)
- **Decision:** MIT.
- **Why:** Prateek's goal says "Use the MIT licence". The research folder's ARCHITECTURE.md section 11 recommended Apache-2.0 for its patent grant; that was a recommendation, the instruction is later and explicit.
- **Alternatives:** Apache-2.0 (patent grant, trademark carve-out), AGPL, BSL (not OSI, fails the launch requirement).
- **Consequence:** the Nigiwai name and brand assets are not licensed for reuse; NOTICE states that.

## D2. Auth: first-party sessions behind a provider interface (2026-10-23)
- **Decision:** the API owns signup, login, sessions and tenant roles (argon2id password hashes, server-side sessions in Postgres, `HttpOnly` `SameSite=Lax` cookie, CSRF token on mutating owner routes). An `IdentityProvider` interface lets a hosted provider replace it.
- **Why:** ARCHITECTURE.md chose Clerk, which needs an account, and the goal forbids creating accounts without approval. A product that cannot run from a clean checkout fails "judge mode works cold".
- **Alternatives:** Clerk (account), Auth.js (adds a second runtime and a user table we would still own), passkeys only (poor recovery story for a first release).
- **Risk:** more security code to own. Mitigated by tests for session fixation, CSRF, brute-force limits and cross-tenant access.

## D3. Bot protection on the public survey: first-party (2026-10-23)
- **Decision:** single-use signed nonce, honeypot field, minimum completion time, per-point burst detection and sliding-window rate limits. Cloudflare Turnstile is an optional adapter that switches on when a site key is configured.
- **Why:** Turnstile needs an account. The architecture already treated Turnstile as one layer of several.
- **Alternatives:** hCaptcha and reCAPTCHA (accounts, third-party scripts on a no-tracker page), proof-of-work CAPTCHA (hurts a 20 s phone survey).

## D4. Hosting: portable containers, no vendor lock-in (2026-10-23)
- **Decision:** the deliverables are container images (`api`, `worker`, `web`), a production Compose file, and infrastructure code for Cloud Run (OpenTofu). Postgres and Redis are plain connection strings, so Neon and Upstash work and so does any self-hosted pair.
- **Why:** no accounts may be created; the product must still be deployable the moment approval arrives.
- **Not verified:** the OpenTofu module cannot be applied without a cloud account. It is reviewed and linted, never applied (status NOT VERIFIED in BUILD_STATE).

## D5. Qloo transport policy (2026-10-23)
Evidence, all VERIFIED on 2026-10-23 against `@qloo/qloo-harness` 0.1.26 and the hackathon host:
1. `qloo api <command>` routes to the legacy endpoint CLI (`search`, `insights`, `entity`, `analyze`, `tags`). It prints entities already unwrapped. `--params '<json>'` merges arbitrary API parameters.
2. For a person-seed combination, REST returns `warnings: [{"type":"not_found", ...}]`; the CLI output has no warnings field (stderr empty). The CLI exposes no response headers either.
3. REST headers on the hackathon host now read `X-Second-RateLimit-Limit: 10` and `X-Month-RateLimit-Limit: 50000` (the research docs recorded 5 and 10,000).
4. `qloo api mcp` is a persistent stdio MCP server, but its `qloo_insights` tool only accepts `type, signal_entities, signal_tags, signal_location, filter_location, take, fields`. It cannot send `filter.tags`, `filter.results.entities`, `filter.popularity.max` or a radius, all of which the product needs.
5. Each CLI call starts a Node process (about 0.5 to 1.5 s overhead per call).
6. `entity` takes one id and has no `--params`; `tags` has no `--params`; `insights --filter-location` maps to `filter.location.query` (the wrong-area trap), so exact points go through `--params {"filter.location": "POINT(lon lat)"}`.
7. On Windows the npm `.cmd` shim breaks JSON arguments (cmd.exe quoting), so the harness is started as `node <package>/dist/bin.js` directly (`resolve_harness_command`).
8. Live parity tests (13, run 2026-10-23) pass: the same `/search` and place `insights` requests return the same entity ids through the harness and through REST.
- **Decision:** the Guard has two transports behind one interface. `HarnessTransport` (the `qloo api` CLI with `--params`) is the **primary** transport, as Prateek instructed, for every call whose result does not depend on `warnings` or headers: all `/search`, `/entities`, `/v2/tags`, `/v2/analysis/compare`, and `insights` without entity seeds. `RestTransport` is used (a) automatically as the fallback when the harness fails or times out, and (b) for `insights` calls that carry entity seeds, because only REST reports dropped seeds (trap 12) and the rate-limit headers the quota ledger needs. A parity test records that both transports return the same entity ids for the same request.
- **Verified live:** insights entities carry `type: "urn:entity"` and the real type in `subtype`, while `/search` and `/entities` use `types[]`; the first synthetic fixtures had this wrong and the live tests caught it. **Why not harness-only:** it would silently lose the dropped-seed warning, which the Guard uses to suppress explainability. **Why not REST-only:** the instruction names the harness, and the kit lists it as the supported event surface.
- **Open for Prateek:** see HUMAN.md H3 (whether to flip the default to REST).

## D6. Toolchain (2026-10-23)
- Python 3.13 (`.python-version`; the code also runs on 3.12) with `uv` (workspace), FastAPI, SQLAlchemy 2 async, Alembic, httpx, pydantic v2. TypeScript with `pnpm`, Next.js App Router for the web app. Task runner: `just` (installed locally, VERIFIED `just 1.57.0`).
- Alternatives rejected are in ARCHITECTURE.md section 2 and still hold.

## D7. Front-end styling: port the design system, not Tailwind (2026-10-23)
- **Decision:** the web app reuses the tokens, components and label system from the research folder's `design/` prototypes (CSS custom properties, self-hosted fonts), packaged as `packages/ui`.
- **Why:** the prototypes were axe-checked in three directions and both themes and carry the product's identity; rewriting them in Tailwind would lose that verification.
- **Alternative:** Tailwind plus Radix (ARCHITECTURE.md). Radix primitives are still used for behaviour where the prototypes had none (dialogs, popovers).

## D8. LLM provider (2026-10-23)
- **Decision:** a provider adapter with structured outputs. The first provider is Anthropic (the Sonnet-class family that ran proof F). Without a configured key every LLM-backed feature falls back to deterministic templates, and the Ask agent says plainly that it is unavailable.
- **Why:** reading `~/.secrets/anthropic-promo.env` is not authorised by the goal; see HUMAN.md H1.

## D9. Operational decisions made while building the platform (2026-10-23)

- **Database and Redis hosts are `127.0.0.1`, not `localhost`.** On Windows with Docker Desktop, `localhost` resolves to IPv6 first and psycopg waited the full 8-second connect timeout on every connection (measured: 127.0.0.1 0.01 s, localhost 8.02 s).
- **Row-level security without FORCE.** The application role does not own the tables, so RLS binds it; the migration role owns the tables and bypasses RLS, which is what lets the `SECURITY DEFINER` functions work on any Postgres host without a BYPASSRLS role. The API checks at start-up that its role is not a superuser, BYPASSRLS or the table owner (`assert_rls_effective`) and refuses to run otherwise. Alternative considered: FORCE RLS plus a BYPASSRLS function owner; rejected because managed Postgres services often cannot grant BYPASSRLS.
- **Tenants are created only by `create_tenant()`.** A direct INSERT into `tenant` or `membership` is denied by policy, so a signed-in user cannot enrol themselves in an existing tenant. Membership writes require the caller to be an owner of the tenant in scope.
- **QR tokens are stored hashed (lookup) and AES-GCM encrypted (so an owner can reprint a poster).** Key derived from the application secret by HKDF. Alternative considered: hash only, which makes a lost poster unrecoverable and forces rotation. Rotation replaces both, so every printed copy of the old code stops working.
- **Minimum three picks per response by default (`min_picks`, owner-adjustable 1 to 10).** PRD M2 says "about 5 picks"; tribes need enough signal per person. Not yet tested against completion rates.
- **No Qloo images are shown on the customer survey (yet).** Loading Qloo's image URLs from a guest's phone would send the guest's address to a third-party host. PRD M3 lists images; this is an open item (BUILD_STATE) until an image route through our own server is checked against Qloo's terms.
- **Free-text district is restricted to a short place name** (no `@`, links or 5+ digit runs), so the field cannot carry an email address or street address.
- **Honeypot, too-fast and burst responses:** a filled honeypot returns a normal-looking success and stores nothing; a response faster than `min_completion_seconds` or beyond 40 per QR point per ten minutes is stored as `quarantined` and excluded from analysis (counted for the owner as "held for review").

## D10. The picker goes to REST first (2026-10-23)

The goal says to use the harness primarily. Measured through the whole application against the live API, 13 calls each way: a search through the harness took 3.2 to 3.6 s (12.4 s for the first), the same search through REST took 0.35 to 1.0 s, and a whole picker journey took 45 s against 12 s. The harness starts a Node process for every call. Type-ahead cannot wait 3.4 s per keystroke pause, so the Guard sends the `picker` purpose to REST first and keeps the harness as the automatic fallback (and as first choice for every other purpose). Configurable with `NIGIWAI_QLOO_REST_FIRST` (comma-separated purposes; empty restores harness-first everywhere). Alternative considered: a persistent harness process (`qloo api mcp`), rejected for now because it exposes only a subset of the insights parameters; worth revisiting for the agent purposes. Review in HUMAN H3.

## D11. Web app decisions (2026-10-23)

- **Direction A, "Riso Counter", is the shipped visual direction.** The design system's own recommendation (DESIGN.md 3.4); no user has compared the directions, so this is a design judgement, not a measured result. The CSS is copied verbatim from the design system by `tools/sync_design.py` (D7), so a fix there carries over; only Direction A's two font families ship.
- **Next.js 16 App Router, React 19, TypeScript 5.9.** TypeScript 7 (the native compiler) was available on npm and was not used: the framework's tooling is built against 5.x. The browser only talks to its own origin; `/api/v1/*` is rewritten to the API, so cookies are first-party and there is no CORS.
- **Owner pages are client components behind a session provider**, not server-rendered with forwarded cookies. The data is private, per-user and changes after every action; nothing there benefits from server rendering or caching.
- **The guest survey keeps a draft in `sessionStorage`** (picks and optional answers, this tab only, cleared on send) so an accidental reload does not lose the picks. The consent text says so.
- **The survey page has no "Taste Card" and promises none.** The prototype's consent screen offered one; it is a Phase 2 feature (M15) and copy must not promise what is not built.
- **A guest's receipt code is the only way to remove their answers**, entered on the survey page. It is shown once, stored only as a hash, and cannot be recovered.
- **`GET .../survey` returns 200 with `null` when the business has no survey yet**, instead of 404, so a first visit does not log a failed request in the browser console (the project's zero-console-errors rule).
- **Quarantine threshold 2 s (`min_completion_seconds`).** A first run at 4 s quarantined a scripted but realistic sitting that restored a saved draft and tapped Start, Continue, Send. A person with a restored draft needs about 2 s; a script is instant. Not tuned against real guests.
- **Container images:** the API image carries Node and the Qloo harness so the harness transport works in production; the web image is a Next.js standalone build. Compose runs migrations as the table owner and the API as the non-owner role.
