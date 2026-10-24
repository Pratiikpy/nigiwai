# Build state

Last updated: 2026-10-24. Read this first after any context reset.

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
| 2 tribes, public start, card | M4, M7, M13, M15, M24 | DONE for what is listed under Phase 2 evidence; open items below (real-QR-pick stability, real-guest timing, M7 accuracy) |
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

## Phase 2 evidence (2026-10-24)
- `just check` green: ruff, eslint, mypy --strict (54 files), tsc, 119 unit tests (Guard and tribes), 7 web unit tests, 154 integration tests. Browser tests in real Chrome, phone and desktop: 20 passed, 4 skipped (the opt-in live specs, run separately below).
- **Tribes engine reproduces the research.** With proof D's own preprocessing feeding the production stability code on the HetRec data, soft K = 3 gave raw stability 0.506 / 0.560 / 0.588 / 0.624 at N = 30 / 60 / 100 / 200 against proof D's 0.506 / 0.561 / 0.586 / 0.623 (`evals/tribes_hetrec_reproduction.py`; the data is research-only and is not in the repo). A planted crowd with no taste structure was refused groups in 5 of 6 trials.
- **Chain, end to end through the browser:** planted crowd of 25, 70 and 200 guests -> job queue -> worker -> `tribe_version` -> My people (empty, thin "25 of 60", provisional "Group A..." and named) -> guest Taste Card placement. Every state: axe clean, zero console errors, screenshots looked at (light, dark, phone, desktop).
- **Taste Card call budget (PRD exit check), live Qloo:** 200 synthetic scans, each a different random three real items sent through the real survey and card endpoints from its own address: mean 1.75 Qloo calls per card, maximum 3, 349 live calls in total, every fill-in `ok`. Instant card answered under 1.5 s in all 200; fill-in wait median 3.5 s, 95th percentile 3.9 s. A first run failed at scan 21 because every scan shared one address and hit the 20-an-hour fill-in limit; the test now gives each scan its own address.
- **Public-lineup start, live:** Mercury Lounge, real MusicBrainz and real Qloo, 33 events and 120 acts, 43 of the first 60 searched matched exactly (72%); proof O measured 69% for this venue. Browser test passed.
- **Audience reading (M7), live:** three real crowds (younger pop, crooners, metal) through the tribes job and the audience step: younger-leaning and leans women; older-leaning and no clear gender lean; older-leaning and leans men, 3 live calls. Browser test passed on phone and desktop with real data. The reference is common knowledge about the acts, the same weak ground truth as proofs K and L; accuracy is **NOT VERIFIED** and the card says so.
- **Proof panel:** invented items shown to the owner: 0 of N (every item must exist in what Qloo returned; a corrupted stored result is reported as invented in a test). Guest-made calls are counted by purpose and never listed.
- Bugs found by the Phase 2 tests and fixed: a refit with unchanged input stored a duplicate version; the related-tastes request put the signal in the exclusions; places near a central London point were landmarks until the category followed the business type; Qloo silently ignores a seed it does not know and answers with popular items, so a dropped seed now makes that card section unavailable; a stale cache survived test runs; a phone nav-drawer race in the browser tests.

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
- **NOT VERIFIED: tribe stability on real QR picks.** The thresholds (60 and 200) come from stability on public listening and Qloo-tag data (proofs D and G), not from guests answering a QR survey. Usefulness of the groups to owners is untested.
- **NOT VERIFIED: the age and gender reading is accurate.** Direction matched common knowledge in the research folder's tests and in the live run above; no survey ground truth exists. It is labelled Modelled, and a group with audience data for fewer than three of its top items gets a plain "not enough" note instead of a reading.
- **NOT VERIFIED: the rate limits** (20 card fill-ins an hour per address, and 40 responses per QR code in ten minutes before new ones are held for review) against a real busy venue; both are choices. One address behind a shared Wi-Fi counts as one.
- **Taste Card:** the richer version (P1) is not built; places as picks are not built (above).
- Lineup start covers music venues in MusicBrainz only; other venue types get "not enough public data yet". MusicBrainz asks for a contact: set `NIGIWAI_LINEUP_CONTACT` before public use (HUMAN H6).
