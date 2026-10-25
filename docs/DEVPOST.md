# Nigiwai: Devpost entry

Text for the Devpost form, in the order its fields appear. The live address and the repository address are the two things only a person can supply (they need hosting and a push, [HUMAN.md](HUMAN.md) H2 and H16); everything else here is ready to paste. Every claim has a test, a measurement or an explicit NOT VERIFIED behind it: [QA.md](QA.md) is the matrix, [DECISIONS.md](DECISIONS.md) the reasoning.

## Name and tagline

**Nigiwai** (賑わい, "the lively bustle of a crowd"). Check an act against your crowd before you book it.

## The problem

A venue that books music decides from gut feel, an act's record elsewhere, or a booker's pitch. None of that says whether the act fits the people who fill *this* room, and an agent asked "who should this venue book?" answers from what is famous. The cost is an empty weeknight, or a Friday that clashes with half the regulars.

## What it does

A venue puts a QR poster on the counter. A guest picks about five things they love in under a minute: bands, films, shows, brands, favourite places. No name, no email, no device identifier. The owner sees who their crowd is as groups (never one guest, never a group under ten), a Today board of the week's quietest hours and up to three actions, a crowd map, and the hero flow, **Soundcheck**: pick any act and see how well it fits each group, as a score from 0 to 100 with its range, why, what to watch for and the nights it suits, with every Qloo call behind it open to read. The result is one page the owner can forward to a booker: the **Booking Brief**.

With no guests yet the crowd comes from the public lineups of the room's past events (MusicBrainz), matched to Qloo by exact id or name, and every score says it is provisional. A stranger can try this without an account on three real venues, or search any other music venue and have it built in a few minutes.

## Why it only works with Qloo

The fit of an act to a group is Qloo's own affinity, ranked among reference acts Qloo returns in the same call. It cannot come from a model's memory: a model can name acts similar to a famous one, but it cannot say how a particular crowd's favourites relate to an obscure act it has never seen. In one run on one demo venue, the acts suggested from the room's own groups scored 89 to 95, and ten real acts checked against the same room scored 2 to 53 (that shows the number moves with the crowd; it does not show the score predicts enjoyment, which is NOT VERIFIED).

| Job | Qloo call | Why Qloo |
|---|---|---|
| Find the act or item a person means | `/search`, typed, by name | A real entity with an id and tags |
| Fit of an act to a group | `/v2/insights`, artist type, the group's favourites as the signal, the act and reference acts as the candidates | One call gives the act and every reference an affinity, so the act is ranked among acts the same group actually picks |
| Suggested acts and a Wildcard | `/v2/insights` neighbours of each group's favourites | Scored the same way |
| What is around, and a guest's favourite place | `/v2/insights` place type with a radius; `/search` place type biased to the room's position | Exact-radius places; the branch near the room |
| Who a group is | `/v2/insights`, demographics | A coarse age and gender lean, labelled Modelled |

## How we built it

- **One guarded path to Qloo** (`packages/qloo-guard`): typed requests that refuse a wrong parameter before it is sent, rules learned from about 660 recorded live calls, a private cache, a rate limiter, a monthly budget by purpose, retries, a circuit breaker and a trace the owner can open. The harness (`qloo api`) is the default transport, REST where it drops warnings or the type-ahead needs speed.
- **Groups that earn their name** (`packages/tribes`): soft groups from the tags of what guests picked, shown only when the crowd is more stable than two shuffled versions of itself (reproduced against the research's real-data numbers: 0.506 / 0.560 / 0.588 / 0.624 at 30 / 60 / 100 / 200 guests against 0.506 / 0.561 / 0.586 / 0.623).
- **A score computed in code** (`packages/fit`): from visible components with a stated weight set, reproducible, with the working shown. The AI only writes the sentence around it, and every item it names must have been returned by a Qloo call during the question.
- **Privacy by construction:** no IP address, user agent or exact time stored with an answer; row-level security on every tenant table, enforced against the application's own database role; an owner's data copy that leaves out every secret and every individual guest's answer.
- **Next.js, FastAPI, Postgres with PostGIS, Redis**, a background worker, a production Docker stack, 22 plain-SQL migrations.

## What we measured, including where Qloo lost

The Evidence page lists fifteen preregistered tests: five won, four tied, five lost, one open. Qloo did not beat an AI alone at open-ended recommendation (on cross-category taste prediction the Qloo-based agent was clearly worse: precision@10 0.038 against 0.107), and its affinity ranked consensus items at chance. Where it measurably did better was staying inside a requested area and honouring filters. So Nigiwai does not present Qloo as a recommender. It uses Qloo to rank an act among a group's own favourites and to check that every act and place exists.

Favourite places were tested before they were built: real Qloo place tags, real acts, planted scenes. Adding two places to three acts raised the recovery of the planted scenes from 0.456 to 0.514 and cost some stability (0.705 to 0.653); reading places through an allowlist (only what a place is, serves and feels like, never who its customers, owners or diets are) cost a little recovery against reading everything (0.514 against 0.572) and is there for privacy, not accuracy (D41).

## Challenges

- **Qloo's place tags describe people.** A place carries up to 200 tags, including "Lgbtq+" customers, owner identity, "Halal" and "Kosher" diets and "Social justice" interests. Grouped, those read as claims about religion, health, orientation and politics. The Guard now stores only a place's taste tags, places that stand for a protected category are never offered, and the filter was read against real searches (a search for "mosque" or "synagogue" returned 16 places each and none was offered; a clinic-and-pharmacy that Qloo lists as a health and beauty shop got through; it is NOT VERIFIED as complete).
- **The research said Qloo loses at the obvious product.** We built the one that survives that: a transparent score and a check that nothing shown is invented.
- **A demo that needs live data cannot wait on Qloo.** The three demo venues are built ahead from real lineups and Qloo and served from storage: a venue opens with suggestions on screen in about a quarter of a second.

## Accomplishments

Tests at every layer, run again from a clean clone: unit, integration against real Postgres and Redis (607), real Chrome on a phone and a desktop profile (axe, zero console errors, screenshots read), and live runs against the real Qloo and MusicBrainz (a venue nobody had prepared was built from nothing in 2.3 minutes and opened). Three real defects were found by checking what a green test had not: a Booking Brief whose group name ran into the count beside it (seen in a sample PDF), a survey toggle whose visible text its accessible name did not contain (found by running the accessibility check on a state it had never been run on), and a Soundcheck banner whose bold guest count broke the sentence onto three lines (seen in a README screenshot).

## What we learned

A transparent score and an honest evidence page matter more to a skeptical reader than a stronger claim. The most useful thing the research did was say where Qloo loses, because it told us where not to build.

## What is not done

Said plainly in [BUILD_STATE.md](BUILD_STATE.md): whether real guests' taste forms groups an owner finds useful, and whether the score predicts a crowd's enjoyment, are NOT VERIFIED and cannot be without guests; the language-model features have run on NVIDIA's and Google's hosted models, not on Claude; nothing is emailed; Qloo's images are not shown on the survey; whether Qloo's terms allow its output to be shown publicly in these forms is a question for Qloo ([HUMAN.md](HUMAN.md) H8, H9, H11, H14).

## Built with

Qloo (Taste API, `qloo api` harness), MusicBrainz (CC0), Next.js, React, FastAPI, PostgreSQL and PostGIS, Redis, scikit-learn, MapLibre with OpenFreeMap tiles, ReportLab, Playwright, Docker.

## Try it

- Live app: set at submission (needs hosting, H2).
- Repository: set at submission (needs a push, H16). MIT licence.
- Without any account: `/try`. Without running anything: the README's sample briefs and [screenshots](screenshots).
