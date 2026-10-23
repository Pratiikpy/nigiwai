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
| 1 foundation | M21 Qloo Guard, M14 platform, M3 picker, M2 survey and QR | IN PROGRESS: Guard core done and live-verified; next the database, platform (M14), picker (M3), survey and QR (M2) |
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
- Guard unit tests: 101 passed (`just test`), ruff clean, mypy --strict clean (27 source files).
- Guard live tests: 13 passed on 2026-10-23 (`NIGIWAI_RUN_LIVE=1 uv run pytest packages/qloo-guard/tests/live -m live`): REST and harness return the same ids; all five place category tags select real places inside the radius; eligibility probe; `/entities` batch with `is_closed`; rate-limit headers reach the ledger.
- Bugs found by live tests and fixed: insights entity types live in `subtype`; the Windows `.cmd` shim breaks JSON arguments.

## Open items and limits
(none yet; every phase appends here)
