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
