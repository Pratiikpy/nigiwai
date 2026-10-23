# Build state

Last updated: 2026-10-23. Read this first after any context reset.

## What this is
Nigiwai (賑わい): a crowd-reading tool for venues; hero flow Soundcheck. Specs live in the research folder `../qloo` (the research folder next to this repo) (PRD.md v0.6, ARCHITECTURE.md with section 14, design/, BUILD_BRIEF.md). This repo is the product. Rules: no push, no public deploy, no accounts, MIT, decisions in docs/DECISIONS.md, human questions in docs/HUMAN.md.

## Resume instructions
1. `cd` into this repository; `git log --oneline` shows verified phases.
2. Read this file, DECISIONS.md and HUMAN.md.
3. Local services: `just up` (Postgres+PostGIS and Redis in Docker; Docker Desktop must be running). Python: `uv sync`. Web: `pnpm install`.
4. Continue at "Current phase" below.

## Phases (PRD section 15, ARCHITECTURE section 12)
| Phase | Scope | Status |
|---|---|---|
| 0 | Repo, tooling, docs | DONE (commit 1) |
| 1 foundation | M21 Qloo Guard, M14 platform, M3 picker, M2 survey and QR | DONE for what is listed under Test evidence; open items below (real-phone timing, 429 onset, places as picks, CI not yet run) |
| 2 tribes, public start, card | M4, M7, M13, M15, M24 | NOT STARTED |
| 3 map-first hero flow | M6, M19 Soundcheck, M9 acts, M23 panel, M22 Brief | NOT STARTED |
| 3b trust and submission | M25 | NOT STARTED |
| 4 Today and chat | M5, M12, M8, M26 | NOT STARTED |
| 5 onboarding | M1 | NOT STARTED |
| 6 moves and ads | M10, M11 | NOT STARTED |
| 7 network and autopilot | M16, M17, M18, M20 | NOT STARTED |

## Verified facts that shape the build (2026-10-23, against the real tools)
- Qloo hackathon key headers: 10 requests/second, 50,000/month. Harness `@qloo/qloo-harness` 0.1.26 (MIT). See DECISIONS D5.
- Docker Desktop 29.1.3 works locally; images `postgis/postgis:16-3.4` and `redis:7-alpine`.
- Node 24.20, pnpm 10.32, uv 0.11, Python 3.11 and 3.13 on the machine (3.12 via uv), just 1.57.
- No LLM key is authorised yet (HUMAN H1).

## Test evidence (2026-10-23)
- `just check` passed: ruff, eslint, mypy --strict, tsc, 103 Guard unit tests, 7 web unit tests, 96 integration tests (API against real Postgres and Redis with a scripted Qloo; the database is rebuilt from the migrations each run).
- Browser tests in real Chrome (`pnpm --filter @nigiwai/web e2e`, against the running API, web app, Postgres, Redis and the live Qloo key): 16 passed on a Pixel 7 profile and a 1440x900 desktop. They cover the owner journey (sign up, venue, survey, poster, overview) and the guest journey (consent, notice sheet, picker, picks, reload keeps the draft, about, send, receipt, removal, what was stored in the database), plus: closed code, search failing then retrying, nothing found, rate limit, expired nonce retried silently, a pick Qloo refuses, wrong receipt. Every state has an axe-core accessibility check (zero violations), a console and failed-request watch (zero), and a screenshot that was looked at (light and dark for the main screens).
- Live Qloo through the whole application: `NIGIWAI_RUN_LIVE=1 uv run pytest apps/api/tests/live` (13 calls, search 0.35 to 1.0 s via REST; 7 of 8 realistic queries put the right item first, the prefix `mur` did not, as PRD M3 already records).
- The production-shaped stack (`docker-compose.prod.yml`) was built and started: migrations as the owner role, API as the non-owner role (the RLS start-up check passed), sign-up through the web proxy returned 201 with a Secure, HttpOnly cookie; both images build; the harness is present in the API image. Torn down afterwards.
- The Qloo key was searched for in the API and web logs, both databases and the whole repository tree: not found.
- Negative controls: with row-level security switched off, 5 of 13 tenancy tests failed, so they do detect a broken boundary.
- Bugs found by the tests and fixed (not exhaustive): insights entity types live in `subtype`; the Windows `.cmd` shim breaks JSON arguments; NUL in a query or name caused a database error; a newline slipped past the district check; an entity already found ineligible was offered again; "yes" was accepted as a boolean; a common password was accepted; `localhost` cost 8 s per connection; a browser reload restored a draft that a 4 s quarantine then wrongly held; the venue form lost its "Saved" message because it remounted; a 404 for "no survey yet" logged a console error; the phone top bar stretched; two clear buttons in the search box; a region landmark was missing.
- The QR in the poster PDF was scanned with OpenCV and decodes to the survey URL (A4, A6, Latin and non-Latin names).

## Open items and limits
- **NOT VERIFIED: speed with real people.** The PRD target (a real phone, median 20 s, five phones) cannot be measured here. The scripted run completes in a few seconds, which says nothing about people. Copy says no time claim.
- **NOT VERIFIED: the 429 onset and concurrent scanners.** No load test against live Qloo has been run; the Guard keeps to 8 requests per second by design and the picker is capped at 20 live searches per sitting.
- **NOT VERIFIED: the CI workflow** (`.github/workflows/ci.yml`) has not run, because nothing is pushed.
- **Places are not pickable** (PRD M3 lists places). Place search needs a location-bounded design and the Guard's place rules; not built.
- **No Qloo images on the survey** (privacy, D9), although PRD M3 lists them.
- **Posters:** names or reward text outside Latin script are left off the printed page (the QR and URL still print) because the bundled fonts are Latin only. The survey and picker handle any script.
- **District is free text** limited to a short place name; a street name without digits would still pass. Replace with an owner-defined list if this proves a problem.
- Minimum three picks and the 2 s quarantine threshold are choices (D9, D11), untested against real guests.
- Reverse proxy must overwrite `X-Forwarded-For` (README), or rate limits can be dodged.
- No team invitations yet (membership roles exist and are enforced; there is no screen to add a member). No password reset or email verification (no email service is authorised, HUMAN H2).
- Production Postgres: migrations as the table-owner role, the API as `nigiwai_app`.
