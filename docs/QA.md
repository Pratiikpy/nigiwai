# Quality assurance

What was tested, how, with what result, and what was not. Written against the product requirements (the research folder's PRD, v0.6) and the standing rule that a green route is not proof: every claim below names the test that makes it, and every gap is named.

Last updated: 2026-10-25, at the commit that carries this file.

## States used

- **PASS**: exercised, with the outcome checked at its source (the database, the file, the API answer, the rendered page) and not only a 200.
- **FAIL**: exercised and wrong. None is open at the time of writing.
- **PENDING**: not yet exercised.
- **BLOCKED**: cannot be exercised here, with what was tried and what is needed.
- **DEVIATION**: built differently from the requirement on purpose, with the reason and where it is recorded.

## How it was run

| Layer | What it is | Run |
|---|---|---|
| Unit | Guard rules, groups (NMF), the Fit score, in-process | `just test`: 148 passed, plus 14 web unit tests |
| Integration | The API on real Postgres 16 with PostGIS and real Redis, the database rebuilt from every migration at the start of each run, Qloo scripted by `fakeqloo.py`, the model scripted, MusicBrainz mocked at the network edge | `just test-integration`: 586 in one full run (21 minutes), plus one test added after that run, which passed alone passed |
| Browser | Real Chrome (not a bundled browser), a Pixel 7 profile and a 1440 x 900 desktop, against the running API, web app, Postgres and Redis; the tests plant real rows or script only the calls to a third party that cannot be reached in a test | `just e2e`: 150 passed, 0 failed, 20 skipped (18 live specs that run only on request, and two specs that are phone-only) across the phone and desktop profiles, 26 minutes |
| Live | Real Qloo, real MusicBrainz, and (opt-in) a real model; spends Qloo quota | `just test-live` (20 passed, 3 skipped (the model-led ones, no model with a key is configured in the clean run) on the clean clone of d3c88d2) and `NIGIWAI_E2E_LIVE=1 just e2e` (14 passed, 4 skipped on the clean clone, including this module's two: a real 34-event venue built from nothing in 1.2 to 2.4 minutes and opened, and a real 6-event venue told in 6 to 19 seconds that it has too few events (phone and desktop)) |
| Clean checkout | A fresh clone, a fresh database, following only the README | commit d3c88d2 (the feature commit; this file's own commit changes only documents): setup, up and migrate exit 0; unit 148 and 14 passed; integration 586 passed in 19 minutes; `just demo` built all three venues; browser 150 passed, 0 failed, 20 skipped in 26 minutes; live browser specs 14 passed, 4 skipped; live Python 20 passed, 3 skipped |

What is scripted in the first three layers is said in each test's header. The live layers use the real services; they do not use the scripted ones.

## The surfaces

Every door to the product, so that a green run on one is not read as a green run on another.

| Surface | Count | Reached by |
|---|---|---|
| API operations (OpenAPI) | 126 | integration tests; the final path segment of every operation appears in at least one API test or browser spec (checked by script, which is a weak check and says only that no operation is untouched) |
| Web pages | 31 | browser specs: the front door, Try it, a demo venue, Evidence, Privacy, Business case, the guest survey, the Taste Card, a shared brief, sign up, sign in, forgot password, invitation, and the owner app's 19 pages |
| Files | 4 | the poster PDF (A4 and A6, decoded with a QR reader), the Booking Brief PDF (public and owner), the data copy (ZIP), the Taste Card share image (a PNG with names only, `test_card.py`) |
| Links that carry a secret | 3 | the survey link (`/s/<token>`), a brief share link (`/b/<token>`, expires, can be turned off), an invitation link (secret after the `#`, hashed at rest) |
| Background work | 6 job kinds and a weekly pass | recompute groups, build public lineup, suggest acts, Grow, Atlas rebuild, build a requested demo venue; the weekly rebuild of the prepared demo venues, which also deletes expired requested ones |
| Roles | 4 | no account, viewer, manager, owner; refusals by role are tested where routes differ by role (writes, the team, the account, the data copy, deleting) |

Every surface was exercised in the states that matter, not only the happy one: signed out, wrong role, another account's id, malformed and junk input, empty input, unknown and expired links, a second use of a one-use secret, a rate limit, and each dependency down (Qloo, MusicBrainz, the model, Postgres in a few cases, Redis).

## Modules

`PRD` is the research folder's PRD. A row's evidence is the file that holds the test; open the file for the cases.

| Module | Status | Evidence | Not covered or deviating |
|---|---|---|---|
| M1 Onboarding | PASS | `test_onboarding.py` (fixed form, five invented owners: café, bar, hotel bar, boutique, music venue, at most eight questions, four required fields protected, nothing saved until confirmed, profile and plan versioned, empty answer never erases), `test_onboarding_model.py` (the model cannot ask outside the checklist or a ninth question, a quote must be words the owner wrote, outage and limit hand over to the form), `onboarding.spec.ts`; live on a real model | **Not run on Claude**, see H12. The live model was an NVIDIA-hosted one, at Prateek's direction. Quality over more than five owners is not measured |
| M2 Survey and QR | PASS | `test_owner.py`, `test_poster.py` (posters decoded with OpenCV's newer QR detector: 60 of 60), `test_public_survey.py`, `owner.spec.ts`, `guest.spec.ts`, `areas.spec.ts` | The PRD's "about 20 seconds on a phone" cannot be measured without people: **NOT VERIFIED**. Posters leave out names or reward text that are not Latin script (the fonts are Latin only); the QR and URL still print |
| M3 Picker | PASS with deviations | `test_picker.py`, `live/test_live_picker.py` (live Qloo), `guest.spec.ts`; stored picks are canonical Qloo entity ids with their type, never free text | **DEVIATION: no places as picks.** The Guard marks places as context, not taste (`qloo_guard.models`), because a place's tags are thin in the research and the effect of place tags on the groups has not been tested; Grow, the Taste Card and the map use places. **DEVIATION: no Qloo images on the survey** (D9): fetching an image from Qloo's host would send the guest's address to a third party. Both are Prateek's to overrule |
| M4 Groups | PASS | `packages/tribes/tests`, `test_tribes.py`, the Last.fm and Qloo reproductions in `evals/` (raw stability 0.506 / 0.560 / 0.588 / 0.624 at N = 30 / 60 / 100 / 200 against the research's 0.506 / 0.561 / 0.586 / 0.623), a planted crowd with no structure refused groups in 5 of 6 trials | **NOT VERIFIED on real QR picks**: the 60 and 200 cut-offs come from public listening and Qloo-tag data, not from guests answering a QR survey. Usefulness to owners is untested |
| M5 Today | PASS | `test_today.py` (quietest stretch, fill an empty chair, book an act, reach people you are missing, the cap of three, thin and day-zero states, decisions per week, no Qloo call), `test_hours*.py`, `today.spec.ts` | The thresholds (20 scans for a quiet stretch, 10 for an hours picture) are choices, not measurements |
| M6 Crowd map | PASS | `test_map.py` (groups, catchment above 10 guests, around you, Gaps from a current Grow run only, Moves), `map.spec.ts`, `maplayers.spec.ts`, `atlas.spec.ts` | **Density is not built** (the PRD allows it only as labelled demand context). Map tiles come from OpenFreeMap; with them blocked the map falls back to a plain background and the list view. The map's pixels are not asserted, only the layers' data and the list |
| M7 My people | PASS | `test_tribes.py`, `test_audience.py`, `people.spec.ts`, `live/test_live_audience.py` | Age and gender readings: **NOT VERIFIED** against survey ground truth; they are labelled Modelled and say so |
| M8 Grow | PASS | `test_grow.py`, `test_grow_model.py`, `grow.spec.ts`, `live/test_live_grow.py` | What Grow finds is unvalidated. On all three real venues the check for place gaps fails, so the page lists places for the crowd as a whole and claims no gap |
| M9 Plan (acts) | PASS | `test_soundcheck.py` (suggestions: top three and a Wildcard from Qloo's neighbours, each scored), `test_sound.py`, `sound.spec.ts`, `soundcheck.spec.ts` | Menu ideas, bridge picks, clash radar and the reaction panel are P1 and not built |
| M10 and M17 Drafts | PASS | `test_drafts.py`, `test_drafts_model.py`, `drafts.spec.ts` | Nothing is sent anywhere, by design; no ad-platform connectors |
| M11 Moves | PASS | `test_moves.py`, `test_moves_model.py`, `moves.spec.ts` (the interval is exact; "inconclusive" and "too early" are answers) | Reads scans only, so a rise is never evidence of revenue |
| M12 Ask | PASS | `test_ask.py` (an item must have come from a Qloo call during the question; an invented name in the sentences is removed; labels must be earned; budget held; outage still answers), `ask.spec.ts`, live on a real model | **Not run on Claude**, see H12. Wording can carry colour no tool returned; only names, ids and numbers are checked |
| M13 Proof | PASS | `test_proof.py`, `people.spec.ts` (the Proof page: every call, what was sent, what came back, invented items counted) | |
| M14 Platform | PASS | `test_auth.py`, `test_tenancy.py` (row-level security, with the negative control: with it off, 5 of 13 tenancy tests fail), `test_team.py`, `test_account.py` (recovery code, password change, deleting an account or a login, **the data copy**), `account.spec.ts`, `team.spec.ts`, `session.spec.ts`, `security.spec.ts`, `viewer.spec.ts`, `errors.spec.ts` | No emailed reset or verification (no email service is authorised, H2 and H13); a recovery code stands in. A download in the Chrome used here is cancelled by the browser for any file, so the click-to-save of the data copy was not seen working; the test fetches the link's address with the same session |
| M15 Taste Card | PASS | `test_card.py`, `guest.spec.ts`, `live/test_live_card*.py`: 200 live scans, mean 1.75 Qloo calls per card, maximum 3, 349 calls, every fill-in ok; the instant card answered in under 1.5 s every time | The richer version (P1) and places as picks are not built. The 20 an hour fill-in limit and the 40 responses per QR in ten minutes are choices, untested against a busy venue |
| M16 Atlas | PASS | `test_atlas.py` (every minimum at the database; no column names a venue; the application role cannot write the table), `atlas.spec.ts` | It cannot show real data at launch (opt-in, minimums); whether Qloo's terms allow a shared cross-business view is **NOT VERIFIED** (H8, H9) |
| M18 Don't-do list | NOT BUILT | n/a | P2 and experimental; the PRD says to release it only after a held-out test, and there is no data on what people dislike to test it against. The Wildcard is the stretch half |
| M19 Fit Verdict | PASS | `packages/fit/tests`, `test_soundcheck.py`: the score is reproducible, every component traces to a Qloo call or a count, thin data shows no number | **NOT VERIFIED that the score predicts enjoyment.** The weights are `v0` and uncalibrated; one observed run on one venue (ten real acts scored 2 to 53, against 89 to 95 for the acts suggested from the room's own groups) shows only that the number moves with the crowd |
| M20 Learning loop | PASS, as described | `test_moves.py` | Counts what was tried; it does not re-weight scores from outcomes (D23, on purpose) |
| M21 Qloo Guard | PASS | `packages/qloo-guard/tests` (the 18 trap classes, parameter whitelists, rate and quota budgets, cache, replay), `live/` | Rate-limit onset against concurrent live scanners is **NOT VERIFIED** |
| M22 Booking Brief | PASS | `test_brief.py` (an unknown, expired or junk share link all say the same thing; links can be turned off), `soundcheck.spec.ts`, `demo.spec.ts` (a PDF downloads without an account) | **DEVIATION: no sample PDFs are committed** for three real venues, because a brief carries Qloo item names and the repository rule is that no Qloo response data is published (H8, H9). The demo venues serve live briefs instead |
| M23 Qloo against an AI | PASS | `test_compare.py` (agreement counted without ranking either side, an act the model does not know is said), `soundcheck.spec.ts` | Run against a real model, not Claude (H12) |
| M24 Public-lineup start | PASS | `test_lineup.py`, `lineup.spec.ts`, `live.spec.ts` (real MusicBrainz and Qloo); **a stranger can search any venue and ask for it** (`test_demo.py` 13 tests, `findvenue.spec.ts`, live: Bowery Ballroom built from nothing in 2.3 minutes and opened, Lincoln Hall told it has too few events in 18 s) | Music venues in MusicBrainz only. A requested venue uses UTC as its time zone, so its brief's date can be a day off. The worker runs one job at a time, so a requested build delays other jobs by minutes (bounded at five a day, not measured under load). The MusicBrainz contact (H6) must be set before public use |
| M25 Trust and submission | PASS with one deviation | Judge mode: `demo.spec.ts`, `test_demo.py`; Evidence, Privacy, Business case and the waitlist: `public.spec.ts`, `test_trust.py`; the submission write-up: `docs/SUBMISSION.md`; feedback: `test_trust.py` | The sample briefs (see M22). The licence is in the repository; the repository's About panel is set only when it is hosted (nothing is pushed). The CI workflow has **never run** because nothing is pushed |
| M26 Sound plan | PASS | `test_sound.py`, `test_sound_model.py`, `sound.spec.ts` | Plan quality is **NOT VERIFIED** against an outside source; the weights are `v0` |

## Across every module

| Check | Status | Evidence |
|---|---|---|
| Row-level security on every tenant table and on the login tables | PASS | `test_tenancy.py`, with the negative control above; the API refuses to start if its role could bypass it |
| No secret leaves the server | PASS | the Qloo key searched for in the API and web logs, both databases and the whole tree: not found; the data copy is searched for every secret and hash in a test; the browser sees no key |
| Headers and content policy | PASS | `security.spec.ts`: a script from another site and a form post to another site are refused in a real page; the page cannot be framed; HSTS on |
| A session that ends mid-work | PASS | `session.spec.ts` |
| Privacy by construction | PASS | no address, user agent or exact time stored with an answer (asserted in the database after a real guest journey) |
| Accessibility | PASS | axe-core on every page and every state the specs reach, light and dark, phone and desktop, zero violations |
| Zero console errors | PASS | every spec attaches console, page-error and request-failed listeners at the start; the only tolerated entries are named in each spec (map tiles from a third party, an aborted link prefetch, and the 503 a venue that is still building answers on purpose) |
| Looked at, not only asserted | PASS | screenshots of every page and state were opened and read: the front door, Try it with its search card, a venue building, failed and ready, a demo venue's Soundcheck, map and brief, the owner app's pages, light and dark, phone and desktop; layout faults found this way were fixed (a search button that wrapped under its field, an hours editor with no styling, a heading level that skipped, a menu marking two items current) |
| Performance | PASS | Lighthouse 100 / 100 / 100 (performance, accessibility, best practices) on the checked public pages with zero layout shift; the judge-mode venue opens with suggestions on screen in 243 to 296 ms against the PRD's 10 s; `perf.spec.ts` |
| A clean checkout runs from the README | PASS | the row above; BUILD_STATE, "Latest run" |
| The production-shaped stack | PASS | `docker-compose.prod.yml` built and started with a throwaway environment: migrations as the owner role to head, the API as the non-owner role (the start-up check passed), both images healthy; a real-user journey in real Chrome through the web port (sign up with a recovery code, a venue and a survey, a poster, an invitation, joining by link, recovery, deleting the account) passed all 14 steps |
| Migrations | PASS | 20 migrations apply from nothing at the start of every integration run; 0020 was applied to an existing database and its downgrade was run |

## Found by testing, and fixed

A sample, not the whole list (the rest is in BUILD_STATE): a stored check that the current suggestions point at was deleted by the clean-up of old checks; a failed rebuild cleared the stored lineup and suggestions; MusicBrainz holds a Mercury Lounge with a longitude of -457; a NUL character in a MusicBrainz record would have made the cache write fail (found while testing a hostile place name for this module's request path, fixed); two visitors asking for the same new venue at the same moment raised a database error (found by a test that forces the race, fixed; the test fails without the fix); a Grow gap read from the wrong place in the stored run; a Today action key that a hash made non-hexadecimal and the decision route refused; the live model tests treating a browser-test stand-in as a real model; a proxy `ECONNRESET` under load (D36).

## Not covered, and why

- **Real people.** No guest, owner or judge used this. Time to complete the survey, whether the groups are useful, whether the Fit score predicts enjoyment, and whether owners act on Today are all **NOT VERIFIED** and cannot be verified without them.
- **Real phones, other browsers.** Chrome only, with a phone profile, not a phone. Safari and Firefox were not run.
- **Claude.** Every model-led feature ran on a scripted model in the automated suites and on an NVIDIA-hosted model in the live runs. Nothing ran on Claude (H12: the key needs a workspace id nobody has supplied).
- **Load.** No concurrent-scanner or load test against live Qloo; the rate-limit onset is not measured. One address behind shared Wi-Fi counts as one.
- **Email.** Nothing is emailed because no email service is authorised (H2, H13).
- **Hosting.** Nothing is deployed; the public address, the domain, TLS termination and a reverse proxy that overwrites `X-Forwarded-For` are the operator's (H2).
- **CI.** The workflow in `.github/workflows` has never run because nothing is pushed.
- **A browser download.** The Chrome used here cancels every download, so the click-to-save of the PDF and ZIP was not seen; the files are fetched with the page's own session and opened instead.
- **Qloo's terms.** Whether showing Qloo-derived names in a public demo, a shared Atlas view or a brief share link is allowed is for Qloo to say (H8, H9, H11).
