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

lint:
    uv run ruff check .
    uv run ruff format --check .

typecheck:
    uv run mypy packages apps

# Unit tests only: no Docker, no network, no Qloo calls.
test:
    uv run pytest -m "not integration and not live"

# Integration tests need `just up`.
test-integration:
    uv run pytest -m integration

# Everything the CI runs.
check: lint typecheck test
