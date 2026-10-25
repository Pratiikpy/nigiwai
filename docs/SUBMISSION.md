# Nigiwai for the Qloo LLM Hackathon

This page answers the six points of the submission guide. The product is live-demoable without an account at `/` and `/try`, and the repository shows it three ways without running anything: screenshots of the owner and guest screens made from a made-up room (no Qloo data in them, [docs/screenshots](screenshots)), three sample Booking Briefs for the demo venues ([docs/samples](samples), which carry Qloo-derived act names and genre labels, so they are subject to the open question in the last section), and the text below.

## 1. The problem

A venue that books music decides who to book from gut feel, from what an act has done elsewhere, or from a booker's pitch. None of that says whether the act fits the people who actually fill this room. Agents are no better: asked "who should this venue book?" they answer from what is famous.

Nigiwai reads a room's crowd and checks an act against it before it is booked. The crowd comes either from guests who answer a QR-code survey of the things they love (no names, emails or device identifiers) or, on day one with no guests, from the public lineups of the room's past events. Qloo's taste graph then says how well an act fits each group in the crowd, and the score is computed in code from those answers, with the working shown.

## 2. Where Qloo is used, and why it fits

Every Qloo call goes through one guarded path (`packages/qloo-guard`): typed requests, rule checks learned from the research, a private cache, a rate limiter, a monthly budget by purpose, and a trace the owner can open. The harness (`@qloo/qloo-harness`, `qloo api`) is the default transport; REST is used where the harness drops `warnings` or headers, and for the type-ahead picker.

| Job | Qloo call | Why Qloo |
|---|---|---|
| Find the act a guest or owner means | `/search` by name, artist type | A real entity with an id and tags, not a string |
| Match a venue's past performers | `/search`, accepted only on an exact normalised name or MusicBrainz id | A miss is dropped, never guessed |
| Fit of one act to one group | `/v2/insights`, artist type, `signal.interests.entities` (the group's favourites), `filter.results.entities` (the act plus reference acts) | One call returns an affinity for the act and every reference, so the act is ranked among acts the same group actually picks |
| Suggested acts and the Wildcard | `/v2/insights`, artist type, `signal.interests.entities` per group | Neighbours of what each group loves, then scored the same way |
| Qloo against an AI alone | `/v2/insights` neighbours of the act, `/search` exact name for every act the model names | Shows which acts exist and where the two lists agree, without ranking either side |
| Who a group is | `/v2/insights`, `filter.type=urn:demographics` | Coarse age and gender lean, labelled Modelled |
| What is around | `/v2/insights`, place type, a location and radius, a category tag | Places inside an exact radius |
| A guest names a favourite place | `/search`, place type, `filter.location` (the room's own position, `lat,lon`) | The point biases the search toward the branch near the room (probed live: it is a bias, not a bound, and the radius parameter changes nothing). A place carries up to 200 tags, so only what a place is, serves and feels like is read or stored; its customers', owners' and diets' tags never are (docs/DECISIONS.md D41) |
| Build any music venue a visitor asks for | `/search` for each past performer, then the Soundcheck calls above | The same code that builds the three demo venues, queued to the worker, capped per network and per day, deleted after seven days (D40) |

Qloo is the reason the score exists: the fit of an act to a group is Qloo's affinity, ranked among reference acts Qloo returned in the same call, so it cannot come from a model's memory. An LLM can name acts similar to a famous one; it cannot say how a particular crowd's favourites relate to an obscure act it has never seen. Section 6 says what this does and does not establish.

## 3. A request and its result, redacted

One Soundcheck asks one question per group of the crowd. For a group whose five most-picked acts are `A1..A5` and a candidate `C`, with up to twenty reference acts `R1..R20` drawn from the same scene:

```
GET /v2/insights
    filter.type                = urn:entity:artist
    signal.interests.entities  = A1,A2,A3,A4,A5
    filter.results.entities    = C,R1,R2,...,R20
    take                       = 50
```

The answer carries an affinity for `C` and for each `R`. The values are not reproduced here. The code turns them into one number: the percentile rank of `C` among the `R` for this group (`group fit`, 0 to 1). Three groups give three calls. The score is then

```
score = round(100 x (0.8 x sum(share_g x fit_g) + 0.2 x peer) x (1 - 0.5 x clash))
```

where `share_g` is the group's share of the crowd, `peer` is omitted (its weight moves to group fit) until there is data on what similar venues book, and `clash` is how far, weighted by group share, the act ranks below the middle of the references. The range shown with the score is bootstrapped from the references. The weights are version `v0`, a starting design that is **not calibrated**; the version is stored with every verdict.

Entity and tag choices: seeds are artists only; an artist is used as a seed only if Qloo's own eligibility probe accepts it (an act it cannot use as a signal is dropped with a note rather than silently ignored); a venue's scenes are found from the tags Qloo returns for its acts. A verdict page lists every call behind it, what was sent, how Qloo answered and whether it came from cache.

## 4. Seeing it

Open the front page, choose a venue, pick a suggested act or search any artist, and open "The Qloo calls behind this score". The three demo venues are Mercury Lounge (New York), The Hideout and Empty Bottle (Chicago); `/try` also builds any other music venue you search for, from its public lineups, in a few minutes. Without running anything: the README shows the sample Booking Briefs, and [docs/screenshots](screenshots) shows a made-up room's Today board, groups, crowd map, Sound plan and brief, the guest survey and the Taste Card on a phone, and the public pages. Every screenshot there is made by `e2e/showcase.spec.ts` from invented guests and acts, with no Qloo data and no real person's details.

## 5. Running it from a clean environment

See the README. In short: Docker, uv, Node 22.19 or newer with pnpm, and just.

```sh
just setup && just up && just migrate
export NIGIWAI_QLOO_KEY_FILE=<a file holding QLOO_API_KEY=...>
just demo          # builds the three demo venues; a few minutes the first time
just dev-api       # second terminal: just dev-web
```

`just check` runs lint, types, unit tests and the integration tests (API against real Postgres and Redis with a scripted Qloo). `just e2e` drives real Chrome through the owner, guest and judge journeys on a phone and a desktop profile, and `just test-live` spends Qloo quota on the real thing.

## 6. Known limitations, and what the results do not establish

- **Qloo does not beat an AI alone at open-ended recommendation.** The Evidence page lists fifteen tests with their limits (five won, four tied, five lost, one open). On cross-category taste prediction the Qloo-based agent was clearly worse than a model alone (precision@10 0.038 against 0.107), and Qloo's affinity ranked consensus items at chance. Where Qloo did measurably better was staying inside a requested area and honouring filters. Nigiwai therefore does not present Qloo as a taste recommender: it uses Qloo to rank an act among a group's own favourites and to check that every act and place exists. Whether the fit score predicts what a crowd will actually enjoy is **NOT VERIFIED**; there is no outcome data.
- **The score's weights are a starting design.** `v0` is not calibrated against held-out picks or bookings.
- **A demo venue is read from public lineups, not guests.** Lineups show who a room booked, not who came, and MusicBrainz holds few events for some rooms (The Hideout has 11). Every demo score is labelled provisional.
- **Groups need guests.** Named groups unlock at 200 guests, a provisional view at 60, because the research measured stability on public data, not on guests answering a QR survey. Usefulness of the groups to owners is untested.
- **The AI-alone panel needs a model key.** Without one it says so. It has run on a real model (NVIDIA's hosted Nemotron, three acts out of three) but not on Claude, whose key needs a workspace id that has not been supplied.
- **Rebuilding a demo venue twice gave different suggestions** from the same matched acts; the cause is unknown.
- **Qloo's terms** on showing Qloo-derived scores, names and neighbours to the public, and on share links, have not been confirmed with Qloo. Item names, up to three genre labels for each act and our own scores are shown; raw Qloo responses and descriptive fields are not republished in the repository or in shared links.
- **Built beyond Soundcheck, with the same honesty rules:** favourite places in the survey (searched near the room, never a place that stands for a religion, a health service, an orientation, a political body or adult entertainment; the filter is judged from real searches and is **NOT VERIFIED** as complete, D41), a copy of an account's data an owner can download, Gaps and Moves layers on the crowd map, a Today board (quiet hours and up to three actions from the owner's own scans), Ask Nigiwai (answers whose items must have been returned by a Qloo call), an onboarding interview that saves nothing until the owner confirms, a Sound plan by time of the week, Grow (ghost customers and the places around, each behind a check it prints), Moves (before and after with a range, often "inconclusive") and Drafts (text with gaps the owner must fill, nothing sent). The model-led parts (Ask, the interview, the AI-alone panel) have been run on a real model and real Qloo, in the API and in a browser, but not on Claude (docs/DECISIONS.md D27).
- **Not built:** the Don't-do list, a public City Taste Atlas (the opt-in groundwork is built and shows nothing until neighbouring venues join), sending anything from Drafts and ad-platform connectors. [docs/BUILD_STATE.md](BUILD_STATE.md) lists what is built, how it was tested and what is open; [docs/HUMAN.md](HUMAN.md) lists what needs a person.
