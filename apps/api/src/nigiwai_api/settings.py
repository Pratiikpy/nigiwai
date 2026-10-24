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
    model_config = SettingsConfigDict(env_prefix="NIGIWAI_", env_file=".env", extra="ignore")

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

    # Run the background worker inside the API process. Fine for one small instance and for development; a production
    # deployment runs `python -m nigiwai_api.worker` as its own service and turns this off.
    embedded_worker: bool = True

    # Public lineups (M24): MusicBrainz event data, CC0. The service asks every client to identify itself with a contact.
    musicbrainz_url: str = "https://musicbrainz.org/ws/2"
    lineup_contact: str = (
        "local development; set NIGIWAI_LINEUP_CONTACT to a URL or email before public use"
    )

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
