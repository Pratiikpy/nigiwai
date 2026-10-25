set shell := ["bash", "-cu"]

default:
    @just --list

# Start Postgres (PostGIS) and Redis for local work and integration tests.
up:
    docker compose up -d --wait

down:
    docker compose down

# Install Python and web dependencies.
setup:
    uv sync --all-packages
    pnpm install

# Apply the database migrations to the local development database.
migrate:
    NIGIWAI_DATABASE_URL_SYNC=postgresql+psycopg://nigiwai:nigiwai-dev-only@127.0.0.1:55432/nigiwai uv run alembic -c db/alembic.ini upgrade head

# Build the three public demo venues (judge mode) from public lineups and Qloo. Needs a Qloo key and the network;
# a few minutes the first time, seconds after. `just demo empty-bottle` builds one.
demo *venue:
    uv run python -m nigiwai_api.demo {{venue}}

# Run the API on :8000 (set NIGIWAI_QLOO_KEY_FILE or QLOO_API_KEY to enable live Qloo search).
dev-api:
    uv run uvicorn nigiwai_api.app:create_app --factory --reload --host 127.0.0.1 --port 8000 --timeout-keep-alive 65

# Run the web app on :3000, proxying /api/v1 to the API.
dev-web:
    pnpm --filter @nigiwai/web dev

lint:
    uv run ruff check .
    uv run ruff format --check .
    pnpm --filter @nigiwai/web lint

typecheck:
    uv run mypy packages/qloo-guard/src packages/tribes/src packages/fit/src apps/api/src
    pnpm --filter @nigiwai/web typecheck

# Unit tests only: no Docker, no network, no Qloo calls.
test:
    uv run pytest -m "not integration and not live"
    pnpm --filter @nigiwai/web test

# Integration tests need `just up`: the API against real Postgres and Redis, with a fake Qloo.
test-integration:
    uv run pytest -m "integration and not live"

# Spends Qloo quota. Needs NIGIWAI_QLOO_KEY_FILE or QLOO_API_KEY.
test-live:
    NIGIWAI_RUN_LIVE=1 uv run pytest -m live

# Browser tests in real Chrome against the running stack (just up, just migrate, just dev-api, a built web app).
e2e:
    pnpm --filter @nigiwai/web build
    pnpm --filter @nigiwai/web e2e

# Everything the CI runs.
check: lint typecheck test test-integration
