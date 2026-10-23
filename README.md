# Nigiwai

Read a room's crowd. Venues put a QR poster on the counter; guests say what they love in about a minute, with no account and no personal details; the owner sees who their crowd is. Taste data comes from [Qloo](https://qloo.com), always through one guarded path.

Status: work in progress. [docs/BUILD_STATE.md](docs/BUILD_STATE.md) says exactly what is built, what is tested and how, and what is open.

## What works today

- **Guest survey** (`/s/<token>`): consent notice, a type-ahead picker backed by a local index and live Qloo search, optional age band, area and budget, a receipt code, and removal of your own answers.
- **Owner app** (`/app`): sign up, describe the venue, configure and publish a survey, create QR codes, download an A4 poster or A6 table card.
- **Qloo Guard** (`packages/qloo-guard`): every Qloo call goes through typed requests, rule checks, a private cache, a rate limiter, a monthly budget and a trace.
- **Privacy by construction**: no IP address, user agent or exact time is stored with an answer; every tenant table is protected by row-level security that the application role cannot bypass.

## Run it locally

You need Docker, [uv](https://docs.astral.sh/uv/), Node 22.19 or newer with pnpm, and [just](https://github.com/casey/just).

```sh
just setup          # Python and web dependencies
just up             # Postgres (PostGIS) and Redis in Docker
just migrate        # create the schema
just dev-api        # API on http://127.0.0.1:8000
just dev-web        # web app on http://localhost:3000   (second terminal)
```

Open http://localhost:3000, create an account, set up the venue, publish the survey and create a QR code. Open the survey link it shows, or scan the QR code from the poster.

**Qloo search.** Without a key the picker serves only items it already knows. To enable live search, save your key as `QLOO_API_KEY=...` in a file kept outside the repository and start the API with `NIGIWAI_QLOO_KEY_FILE=<that file>`. The key is read on the server only and is never sent to a browser.

## Tests

```sh
just test               # unit tests, no services needed
just test-integration   # API against real Postgres and Redis (needs just up)
just test-live          # spends Qloo quota; needs a key
just e2e                # real Chrome against the running stack
just check              # lint, types, unit and integration tests
```

## Deploy

`docker-compose.prod.yml` runs Postgres, Redis, a one-shot migration, the API and the web app. Copy `.env.prod.example` to `.env.prod`, fill it in and run `docker compose --env-file .env.prod -f docker-compose.prod.yml up -d --build`. Put a TLS-terminating reverse proxy in front of the web port that **overwrites** `X-Forwarded-For`; the API trusts that header for rate limiting. Migrations run as the table-owner role and the API as a separate non-owner role, and the API refuses to start if it is connected as a role that would bypass row-level security.

## Layout

| Path | What |
|---|---|
| `packages/qloo-guard` | The only code that talks to Qloo |
| `apps/api` | FastAPI service: accounts, tenancy, picker, survey, posters |
| `apps/web` | Next.js app: guest survey and owner screens |
| `db` | Alembic migrations (plain SQL) |
| `docs` | Decisions, build state, open questions |

## Licence

MIT. Third-party fonts and data are credited in [NOTICE.md](NOTICE.md). Qloo's own terms govern use of its API and data.
