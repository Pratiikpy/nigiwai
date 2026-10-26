# Nigiwai: Devpost entry

Paste these into the Devpost form, field by field. Live app: https://nigiwai.knole.me · Repository: https://github.com/Pratiikpy/nigiwai (MIT) · Video: https://youtu.be/3dFhP7JRtY0. Every claim below has a test, a measurement or an explicit NOT VERIFIED behind it: [QA.md](QA.md) is the matrix, [DECISIONS.md](DECISIONS.md) the reasoning.

## Project name (60 characters)

Nigiwai: Soundcheck any act on your crowd

## Elevator pitch (200 characters)

Qloo's taste graph scores how well an act fits each group in a venue's crowd, before it is booked. The score is computed in code and every Qloo call is shown. Live, open source, no sign-up to try.

## About the project (the "Project details" field; Markdown)

**Nigiwai** (賑わい, "the lively bustle of a crowd") answers one question for every room that books music: **will this act fit the people who actually fill this room?**

It reads a venue's crowd from what its guests love, asks **Qloo's taste graph** how an act relates to each group in that crowd, and returns a decision with its working: a fit from 0 to 100, its likely range, how each group ranks it, why, what to watch for, and the nights it suits. **Every Qloo call behind the score is on the page.**

**Live app (no account): https://nigiwai.knole.me/try** · **Video: https://youtu.be/3dFhP7JRtY0** · **Code (MIT): https://github.com/Pratiikpy/nigiwai**

### Try it in 60 seconds

1. Open [/try](https://nigiwai.knole.me/try) and choose a real room: Mercury Lounge (New York), The Hideout or Empty Bottle (Chicago). Each is read from the public lineups of its past events and matched to Qloo.
2. Pick a suggested act, or search any artist. You get the score and the working.
3. Open **"The Qloo calls behind this score"**: the real `/v2/insights` request and Qloo's answer, with timings and whether it came from cache.
4. Open **"Qloo and an AI alone"**: the same question put to a language model with no tools, beside Qloo's answer.
5. Or be the guest: scan the survey link, pick five things you love, get a Taste Card.

### The problem

A venue books acts from gut feel, an act's record elsewhere, or a booker's pitch. None of that says whether the act fits **this** crowd, and an AI asked "who should this venue book?" answers from what is famous. The cost is an empty weeknight, or a Friday that clashes with half the regulars.

### What it does

- **A crowd, without knowing anyone.** A QR poster on the counter. A guest picks about five things they love in under a minute: no name, no email, no device identifier. The owner sees groups, never one guest and never a group under ten. With no guests yet, the crowd is read from the public lineups of the room's past events (MusicBrainz) and matched to Qloo, and every score says it is provisional.
- **Soundcheck (the hero flow).** Pick any act. The score is computed in code from Qloo's answers; the formula, the weights and every Qloo call behind it are shown.
- **Qloo against an AI alone.** Beside every Soundcheck. In our own demo the AI said it did not know the act and gave no list, while Qloo returned six real neighbours, each checked against its graph.
- **A decision to act on.** A one-page **Booking Brief** to forward to a booker; a **Sound plan** (which acts at which time of the week); a **crowd map**; a **Today** board (the quietest hours and up to three actions, each with its reason); **Grow** (who else might come, and places like yours); **Moves** (did a change work, with the doubt shown); **Ask Nigiwai** (every item it names must have come back from a Qloo call).

### Why it only works because of Qloo

Qloo asked for "the thing that only works because it knows what people love". Nigiwai is built so that can be checked:

- **The score is Qloo's, not a model's.** For each group, one `/v2/insights` call carries the group's five favourites as the signal and the act plus up to twenty reference acts as the filter. The answer ranks the act among acts that same group actually picks. A model can name acts similar to a famous one; it cannot say how a particular crowd's favourites relate to an obscure act it has never seen.
- **Remove Qloo and there is no score.** The AI-alone panel shows what is left.
- **Nothing is invented.** Every act or place the product names must have come back from a Qloo call during the question; a name no call returned is removed before you see it.

### How we use Qloo

Seven jobs through three endpoints (`/search`, `/v2/insights`, `/entities`):

- **Find the act or place a person means:** `/search`, artist or place type (places are biased to the room's position).
- **Match a venue's past performers:** `/search`, accepted only on an exact normalised name or MusicBrainz id; a miss is dropped, never guessed.
- **Fit of one act to one group:** `/v2/insights`, artist type, `signal.interests.entities` plus `filter.results.entities`.
- **Suggested acts and the Wildcard:** `/v2/insights` per group, scored the same way.
- **Qloo against an AI alone:** neighbours from `/v2/insights`, and `/search` by exact name for every act the model names.
- **Who a group is:** `/v2/insights` with `filter.type=urn:demographics`, labelled *modelled*.
- **What is around:** `/v2/insights`, place type, a location and radius.

Every call goes through **one guarded path** (`packages/qloo-guard`): typed requests that refuse a wrong parameter before it is sent, rules learned from about 660 recorded live calls, a private cache, a rate limiter, a monthly budget by purpose, retries, a circuit breaker, and a trace the owner can open.

### The Qloo mindset, built in

- **Taste without identity.** "Knowing what someone may like should not require knowing who they are." No name, email, IP address, user agent or exact time is stored with an answer; a group is shown only at ten or more guests; every table is row-level-secured, enforced against the application's own database role.
- **Judgment, with reasons.** Not a list: a fit, its range, each group's rank, what would change it, what to watch.
- **Grounded, then narrated.** Qloo picks the entities; a model only writes the sentence around them, and code checks the sentence.
- **Honest about its limits.** Every number says whether it was *measured*, *observed* or *modelled*.

### What we measured, including where Qloo lost

We ran **fifteen preregistered tests** against an AI alone and against free-data agents, and published them on the Evidence page: **five won, four tied, five lost, one open.** Qloo did **not** beat a language model at open-ended recommendation. Where it measurably earned its place: staying inside a requested area and honouring filters (all 239 results inside the radius), and ranking an act among a group's own favourites. So Nigiwai does not sell Qloo as a recommender; it uses Qloo where the test said it works. We would rather show a judge where Qloo lost than make a claim they can disprove in a minute.

### Design: a complete product, not a proof of concept

A guest on a phone (consent, a type-ahead picker, a Taste Card), an owner on a desktop (crowd map, groups, Soundcheck, Sound plan, Booking Brief, Today), and the public pages, in light and dark, with accessibility checks and zero console errors. Empty, thin-data and error states say what is missing and what would unlock more, instead of guessing.

### Impact: who pays, and why

A venue's booker or owner. Independent live-music venues and bars that book acts first; restaurants, breweries, hotel bars, festivals and promoters next; the Sound plan reaches any room with a speaker. A subscription per venue is the hypothesis (the price is untested). Nigiwai does not resell Qloo output, which Qloo's terms forbid: the owner pays for the crowd, the decision and the brief.

### A non-obvious use of Qloo

Instead of asking Qloo for "more like this", Nigiwai uses it to **rank a specific act among a crowd's own favourites, group by group**, and to start a venue's crowd from public lineups when it has no guests yet. The same call powers the score, the suggestions, the Sound plan and the Booking Brief.

### How it is built, and how it was checked

Next.js 16, FastAPI, Postgres with PostGIS and row-level security, Redis, a background worker, 22 plain-SQL migrations, a production Docker stack. **612 integration tests** against real Postgres and Redis, **158 browser tests** in real Chrome on a phone and a desktop, live runs against the real Qloo and MusicBrainz APIs, and a clean clone that passed every stage from the README. A stranger's smoke test (sign up, publish a survey, a guest answers on a phone, the owner reads it, the account is deleted) passes against the live site.

### Honest limits

Whether the fit score predicts what a crowd will enjoy is **NOT VERIFIED** (there is no outcome data), and the weights are an uncalibrated starting design. Groups need guests (60 for a provisional view, 200 for names), and their usefulness to owners is untested. The language-model features have run on NVIDIA's and Google's hosted models, not on Claude. A "Don't-do list" of acts a main group ranks poorly is built as an idea only, because the held-out test it needs cannot be run without data on what crowds dislike. Whether Qloo's terms allow its output to be shown publicly in these forms is a question for Qloo.

### What's next

Pilot with real venues and learn which groups owners find useful; calibrate the score against real bookings; agree the terms for showing Qloo output publicly; move hosting to durable infrastructure.

## Built with

Qloo (Taste API: search, insights, entities), MusicBrainz, Next.js, React, FastAPI, PostgreSQL and PostGIS, Redis, scikit-learn, MapLibre with OpenFreeMap tiles, Google Gemini (language-model features), Cloudflare Tunnel, Playwright, Remotion, Docker.

## Try it

- Live app, no account: https://nigiwai.knole.me/try
- Repository (MIT, licence shown in About): https://github.com/Pratiikpy/nigiwai
- Video: https://youtu.be/3dFhP7JRtY0
