"""Build the judge-mode demo venues: `python -m nigiwai_api.demo [slug]`.

It needs Qloo configured and the network (MusicBrainz for the lineups). Each venue takes a few minutes the first time, since
every act is looked up in Qloo; a second run is fast because the answers are cached. A venue that fails is reported and the
others still build. Exit status is non-zero when any venue failed.
"""

from __future__ import annotations

import asyncio
import logging
import sys

from .app import build_state, close_state
from .services import demo as demo_service
from .settings import get_settings


async def run(only: str | None) -> dict[str, str]:
    settings = get_settings().model_copy(update={"embedded_worker": False})
    state, tasks = await build_state(settings)
    try:
        return await demo_service.seed(
            state.engine,
            state.guard,
            state.musicbrainz,
            state.llm,
            state.limiter,
            settings.llm_daily_limit,
            only,
        )
    finally:
        await close_state(state, tasks)


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    only = args[0] if args else None
    known = {s.slug for s in demo_service.SPECS}
    if only is not None and only not in known:
        print(
            f"unknown demo venue {only!r}; choose from: {', '.join(sorted(known))}", file=sys.stderr
        )
        return 2
    logging.basicConfig(level=logging.INFO)
    outcome = asyncio.run(run(only))
    for slug, result in outcome.items():
        print(f"{slug}: {result}")
    return 0 if all(r == "ready" for r in outcome.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
