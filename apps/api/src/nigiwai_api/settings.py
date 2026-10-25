"""Application settings, read from NIGIWAI_* environment variables. Secrets are never given defaults in production."""

from __future__ import annotations

import secrets
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

DEV_SECRET = "dev-only-secret-change-me-in-real-environments"  # noqa: S105 - rejected outside development


class Settings(BaseSettings):
    # An empty value is the same as an unset one: the production Compose file passes optional settings through as empty strings.
    model_config = SettingsConfigDict(
        env_prefix="NIGIWAI_", env_file=".env", extra="ignore", env_ignore_empty=True
    )

    env: Literal["development", "test", "production"] = "development"

    database_url: str = (
        "postgresql+asyncpg://nigiwai_app:nigiwai-app-dev-only@127.0.0.1:55432/nigiwai"
    )
    redis_url: str = "redis://127.0.0.1:56379/0"

    secret_key: str = DEV_SECRET
    session_cookie: str = "nigiwai_session"
    session_ttl_days: int = 14
    cookie_secure: bool = False
    trust_proxy: bool = (
        False  # read the client address from X-Forwarded-For (only behind a trusted proxy)
    )
    cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:3000"])

    # Qloo
    qloo_base_url: str = "https://hackathon.api.qloo.com"
    qloo_key_file: str | None = None
    qloo_transport: Literal["harness", "rest"] = "harness"
    qloo_mode: Literal["live", "record", "replay"] = "live"
    qloo_harness_home: str | None = None
    # Purposes sent to REST before the harness (comma separated). Default: the type-ahead picker and the two batch jobs that make dozens of calls, because the
    # harness adds about 2.4 s of Node start-up per call. Empty means every purpose prefers the harness.
    qloo_rest_first: str = "picker,lineup,tribes"

    # The language model behind the "AI alone" comparison (M23). Without a key file the comparison says so and the rest of
    # the product is unaffected. The key is read on the server only and is never sent to a browser or logged.
    anthropic_key_file: str | None = None
    anthropic_workspace_id: str | None = (
        None  # needed only when the key is not scoped to one workspace
    )
    llm_provider: Literal["anthropic", "openai"] = (
        "anthropic"  # openai: any OpenAI-compatible chat completions service
    )
    llm_key_file: str | None = (
        None  # the key for an OpenAI-compatible service (or NIGIWAI_LLM_API_KEY in the environment)
    )
    llm_extra_body: str | None = (
        None  # JSON merged into every request of an OpenAI-compatible service
    )
    llm_model: str = "claude-sonnet-5-5"
    llm_base_url: str | None = None  # a local test server, or a gateway
    llm_timeout_seconds: float = 25.0
    llm_daily_limit: int = 100  # model calls per account per day
    ask_daily_limit: int = 40  # questions put to Ask Nigiwai per account per day
    onboarding_daily_limit: int = 80  # model steps in the onboarding interview per account per day

    # The public demo venues (judge mode) let anyone run new checks, and each one calls Qloo. These cap the whole site per
    # day, on top of a per-network limit, and sit well inside the Guard's monthly share for the fit class (5,000 calls, so
    # about 1,250 new checks a month at four calls each). Raise them only with the Qloo allowance in mind.
    demo_runs_per_day: int = 60
    demo_searches_per_day: int = 300
    demo_compares_per_day: int = 100

    # Run the background worker inside the API process. Fine for one small instance and for development; a production
    # deployment runs `python -m nigiwai_api.worker` as its own service and turns this off.
    embedded_worker: bool = True

    # Public lineups (M24): MusicBrainz event data, CC0. The service asks every client to identify itself with a contact.
    musicbrainz_url: str = "https://musicbrainz.org/ws/2"
    lineup_contact: str = (
        "local development; set NIGIWAI_LINEUP_CONTACT to a URL or email before public use"
    )

    # The crowd map finds a neighbourhood from the name a guest typed, through OpenStreetMap's Nominatim (at most one
    # request a second, identified by the contact above, every answer cached).
    nominatim_url: str = "https://nominatim.openstreetmap.org"

    # Public survey
    nonce_ttl_seconds: int = 3600
    # A response faster than this is held for review. A person with a restored draft needs about 2 s (Start, Continue,
    # Send); a script is instant. See docs/DECISIONS.md D9.
    min_completion_seconds: float = 2.0
    picker_calls_per_session: int = 20

    # Where the survey page lives: used to print QR posters
    public_base_url: str = "http://localhost:3000"

    # Uploaded or generated assets
    data_dir: Path = Path(".nigiwai-data")

    @model_validator(mode="after")
    def _production_needs_real_secrets(self) -> Settings:
        if self.env == "production":
            if self.secret_key == DEV_SECRET or len(self.secret_key) < 32:
                raise ValueError(
                    "NIGIWAI_SECRET_KEY must be set to a random value of at least 32 characters"
                )
            if not self.cookie_secure:
                raise ValueError("NIGIWAI_COOKIE_SECURE must be true in production")
        return self


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


def new_secret() -> str:
    return secrets.token_urlsafe(48)
