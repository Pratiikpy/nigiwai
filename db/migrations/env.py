"""Alembic environment. Migrations are plain SQL files run in order; the URL comes from the environment."""

from __future__ import annotations

import os

from alembic import context
from sqlalchemy import create_engine, pool

config = context.config


def _url() -> str:
    url = os.environ.get("NIGIWAI_DATABASE_URL_SYNC")
    if not url:
        raise RuntimeError(
            "set NIGIWAI_DATABASE_URL_SYNC to the migration role's connection string"
        )
    return url


def run_migrations_online() -> None:
    engine = create_engine(_url(), poolclass=pool.NullPool)
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=None)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    context.configure(url=_url(), literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()
else:
    run_migrations_online()
