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
| 1 foundation | M21 Qloo Guard, M14 platform, M3 picker, M2 survey and QR | IN PROGRESS: Guard (M21), database, API platform (M14), picker backend (M3), survey and QR backend (M2) built and tested; NOT DONE: the web app (survey page and owner screens), Dockerfiles, a live-Qloo run of the picker, the `just check` recipe over the whole workspace |
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

## Test evidence
- `uv run pytest` (whole workspace, run 2026-10-23): 196 passed, 13 skipped (the live Qloo tests, which spend quota and need `NIGIWAI_RUN_LIVE=1`). ruff clean, mypy --strict clean on `apps/api/src` and `packages/qloo-guard/src`. The API tests need `just up` (Postgres, Redis) and rebuild the test database from the migrations on every run.
- API tests by area: auth 17, tenancy and RLS 13, public survey 23, picker 14, owner 10, poster 5, platform 13. Negative control: with RLS disabled on `business` and the membership policy opened, 5 of the 13 tenancy tests failed, so they do detect a broken boundary.
- Guard live tests: 13 passed on 2026-10-23 (`NIGIWAI_RUN_LIVE=1 uv run pytest packages/qloo-guard/tests/live -m live`): REST and harness return the same ids; all five place category tags select real places inside the radius; eligibility probe; `/entities` batch with `is_closed`; rate-limit headers reach the ledger.
- Bugs found by tests and fixed: insights entity types live in `subtype`; the Windows `.cmd` shim breaks JSON arguments; a NUL byte in a picker query or a name caused a database error (now rejected or cleaned); a newline in the district slipped past the check; the picker re-offered an entity already found ineligible; "yes" was accepted as a boolean and "51.5" as a number (the API is now strict); a common password ("password1234") was accepted (now refused against a bundled list); `localhost` cost 8 s per database connection on this machine (now `127.0.0.1`).
- The poster QR was scanned from the rendered PDF with OpenCV and decodes to the survey URL (A4, A6, Latin and non-Latin names). Looked at on screen: layout is clean.

## Open items and limits
- Web app not built yet (Phase 1 remainder). Everything in this file marked tested was tested through the HTTP API, not through a browser.
- The picker was run against live Qloo through the whole application once (2026-10-23, `NIGIWAI_RUN_LIVE=1 uv run pytest apps/api/tests/live`): 13 calls, all `ok`, 8 realistic queries returned the right top result for 7 (the prefix `mur` returned books, not Murakami, as PRD M3 already records), search 0.35 to 1.0 s via REST, probes `eligible=True` for 5 of 5, a 5-pick response stored. The other API tests use a scripted stand-in for Qloo.
- Poster: names or reward text with characters outside Latin script are left off the page (the QR and URL still print) because the bundled fonts are Latin only. The picker and survey handle any script; the print layout does not yet.
- No Qloo images on the survey page (privacy, DECISIONS D9). PRD M3 asks for images.
- District is free text limited to a short place name; a street name without digits would still pass. Replace with an owner-defined list of districts if this proves a problem.
- Minimum three picks is a choice (D9), untested against completion.
- Production Postgres must run migrations as the table-owner role and the API as the separate non-owner role `nigiwai_app`; the API refuses to start otherwise.
