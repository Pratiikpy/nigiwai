# Nigiwai: Devpost entry

Paste these into the Devpost form, field by field. Live app: https://nigiwai.knole.me · Repository: https://github.com/Pratiikpy/nigiwai (MIT) · Video: https://youtu.be/3dFhP7JRtY0. Every claim below has a test, a measurement or an explicit NOT VERIFIED behind it: [QA.md](QA.md) is the matrix, [DECISIONS.md](DECISIONS.md) the reasoning.

## Project name (60 characters)

Nigiwai: Soundcheck any act on your crowd

## Elevator pitch (200 characters)

Qloo's taste graph scores how well an act fits each group in a venue's crowd, before it is booked. The score is computed in code and every Qloo call is shown. Live, open source, no sign-up to try.

## About the project (the "Project details" field; Markdown)

**Nigiwai** (賑わい, "the lively bustle of a crowd") answers one question for every room that books music: *will this act fit the people who actually fill this room?*

### The problem

A venue books acts from gut feel, an act's record elsewhere, or a booker's pitch. None of that says whether the act fits *this* crowd, and an AI asked "who should this venue book?" answers from what is famous. The cost is an empty weeknight, or a Friday that clashes with half the regulars.

### What it does

- **A crowd, without knowing anyone.** A QR poster on the counter. A guest picks about five things they love (bands, films, shows, brands, favourite places) in under a minute: no name, no email, no device identifier. The owner sees groups, never one guest and never a group under ten. With no guests yet, the crowd is read from the public lineups of the room's past events (MusicBrainz) and matched to Qloo, and every score says it is provisional.
- **Soundcheck (the hero flow).** Pick any act. Get a fit from 0 to 100 with its likely range, how it ranks for each group, why, what to watch for and the nights it suits. The score is computed in code from Qloo's answers; the formula, the weights and **every Qloo call behind it are on the page**.
- **Qloo against an AI alone.** Beside every Soundcheck, the same question goes to a language model with no tools. In our own demo it said it did not know the act and gave no list, while Qloo returned six real neighbours, each checked against its graph.
- **What to do with it.** A Booking Brief to forward to a booker, a Sound plan (which acts at which time of the week), a crowd map, a Today board (the quietest hours and up to three actions), Grow (who else might come, and the places like yours), Moves (did a change work, with the doubt shown), and Ask Nigiwai (answers whose every item must have come back from a Qloo call).

### Why it only works because of Qloo

The fit of an act to a group is **Qloo's own affinity, ranked among reference acts Qloo returns in the same call**. A model can name acts similar to a famous one; it cannot say how a particular crowd's favourites relate to an obscure act it has never seen. One `/v2/insights` call per group: the group's five favourites as the signal, the act plus up to twenty reference acts as the filter.

Qloo is used for seven jobs, through three endpoints:
- Find the act or place a person means: `/search` (artist or place; places biased to the room's position).
- Match a venue's past performers: `/search`, accepted only on an exact normalised name or MusicBrainz id. A miss is dropped, never guessed.
- Fit of one act to one group: `/v2/insights`, artist type, `signal.interests.entities` plus `filter.results.entities`.
- Suggested acts and the Wildcard: `/v2/insights` per group, scored the same way.
- Qloo against an AI alone: `/v2/insights` neighbours and `/search` by exact name for every act the model names.
- Who a group is: `/v2/insights` with `filter.type=urn:demographics`, labelled Modelled.
- What is around: `/v2/insights`, place type, a location and radius; and `/entities` to read items back.

Every call goes through **one guarded path** (`packages/qloo-guard`): typed requests that refuse a wrong parameter before it is sent, rules learned from about 660 recorded live calls, a private cache, a rate limiter, a monthly budget by purpose, retries, a circuit breaker, and a trace the owner can open.

### What we measured, including where Qloo lost

We ran **fifteen preregistered tests** against an AI alone and against free-data agents, and published them on the Evidence page: five won, four tied, five lost, one open. Qloo did **not** beat a language model at open-ended recommendation, and its affinity ranked consensus items at chance. Where it measurably earned its place: staying inside a requested area and honouring filters (all 239 results inside the radius), and ranking an act among a group's own favourites. So Nigiwai does not sell Qloo as a recommender. It uses Qloo where the test said it works, and labels every number *measured*, *observed* or *modelled*.

### Privacy by construction

"Knowing what someone may like should not require knowing who they are." No name, email, IP address, user agent or exact time is stored with an answer. A group is shown only at ten or more guests. Every tenant table is row-level-secured, enforced against the application's own database role. Qloo's place tags describe people (customers, owners, diets, beliefs), so the Guard stores only a place's taste tags and never offers a place that stands for a religion, a health service, an orientation, a political body or adult entertainment.

### Who pays

A venue's booker or owner: an independent live-music venue or a bar that books acts first; restaurants, breweries, hotel bars, festivals and promoters next; the Sound plan reaches any room with a speaker. A subscription per venue is the hypothesis; the price is untested and none is shown. Nigiwai does not resell Qloo output (Qloo's terms forbid it): the owner pays for the crowd, the decision and the brief.

### How it is built, and how it was checked

Next.js 16, FastAPI, Postgres with PostGIS and row-level security, Redis, a background worker, 22 plain-SQL migrations, a production Docker stack. **612 integration tests** against real Postgres and Redis, **158 browser tests** in real Chrome on a phone and a desktop profile (accessibility checks, zero console errors), live runs against the real Qloo and MusicBrainz APIs, and a clean clone that passed every stage from the README. Hosted at nigiwai.knole.me; a stranger's smoke test (sign up, publish, a guest answers on a phone, the owner reads it, the account is deleted) passes against the live site.

### Honest limits

Whether the fit score predicts what a crowd will enjoy is **NOT VERIFIED** (there is no outcome data), and the weights are an uncalibrated starting design. Groups need guests (60 for a provisional view, 200 for names), and their usefulness to owners is untested. The language-model features have run on NVIDIA's and Google's hosted models, not on Claude. A "Don't-do list" of acts a main group ranks poorly is built as an idea only, because the PRD's held-out test cannot be run without data on what crowds dislike. Whether Qloo's terms allow its output to be shown publicly in these forms is a question for Qloo.

## Built with

Qloo (Taste API: search, insights, entities), MusicBrainz, Next.js, React, FastAPI, PostgreSQL and PostGIS, Redis, scikit-learn, MapLibre with OpenFreeMap tiles, Google Gemini (language-model features), Cloudflare Tunnel, Playwright, Docker.

## Try it

- Live app, no account: https://nigiwai.knole.me/try
- Repository (MIT, licence shown in About): https://github.com/Pratiikpy/nigiwai
- Video: https://youtu.be/3dFhP7JRtY0
