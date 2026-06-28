"""Alembic schema bootstrap — the boot-time replacement for `create_all`.

`ensure_schema()` brings the database to head on startup and handles three cases:

- **fresh DB** — no tables → `upgrade head` creates everything from the baseline.
- **managed DB** — has `alembic_version` → `upgrade head` applies pending revisions.
- **legacy DB** — tables exist (old `create_all`) but no `alembic_version` → `stamp head`
  marks the baseline as already applied, then `upgrade head` runs anything newer.

Alembic's online env runs its own `asyncio.run`, so the synchronous `command.*` calls are
executed in a worker thread (no running event loop there) via `asyncio.to_thread`.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import inspect

from armarius.infrastructure.database.engine import get_engine

_BACKEND_ROOT = Path(__file__).resolve().parents[3]
_ALEMBIC_INI = _BACKEND_ROOT / "alembic.ini"
_SCRIPT_LOCATION = _BACKEND_ROOT / "armarius" / "infrastructure" / "alembic"


def _config() -> Config:
    cfg = Config(str(_ALEMBIC_INI))
    cfg.set_main_option("script_location", str(_SCRIPT_LOCATION))
    return cfg


def _run(legacy: bool) -> None:
    cfg = _config()
    if legacy:
        command.stamp(cfg, "head")
    command.upgrade(cfg, "head")


async def ensure_schema() -> None:
    engine = get_engine()
    async with engine.connect() as conn:
        tables = await conn.run_sync(lambda c: set(inspect(c).get_table_names()))
    legacy = bool(tables) and "alembic_version" not in tables
    await asyncio.to_thread(_run, legacy)
