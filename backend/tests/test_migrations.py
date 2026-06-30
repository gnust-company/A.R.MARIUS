"""Sprint 3 — Alembic 0002 applies and reverses cleanly on a throwaway database.

Drives the real `alembic` command stack (env.py → async engine), pointed at an isolated
SQLite file via `settings.database_url`. A plain (sync) test so env.py's own
`asyncio.run` has no running loop to collide with.
"""

from __future__ import annotations

from alembic import command
from sqlalchemy import create_engine, inspect

from armarius.infrastructure.database.migrations import _config
from armarius.shared.config import settings

_SPRINT3 = "468899ef9a27"
_BASELINE = "a40098b66ac7"


def test_migrations_upgrade_head_then_downgrade_base(tmp_path, monkeypatch) -> None:
    db = tmp_path / "mig.db"
    monkeypatch.setattr(settings, "database_url", f"sqlite+aiosqlite:///{db}")
    cfg = _config()

    command.upgrade(cfg, "head")

    insp = inspect(create_engine(f"sqlite:///{db}"))
    tables = set(insp.get_table_names())
    assert {"roles", "seat_grants", "labels"} <= tables
    project_cols = {c["name"] for c in insp.get_columns("projects")}
    assert {"status", "objective", "settings", "created_by_user_id"} <= project_cols
    marius_cols = {c["name"] for c in insp.get_columns("mariuses")}
    assert {"invite_status", "probe_attempts", "next_probe_at", "turn_started_at"} <= marius_cols
    insp.bind.dispose()

    # Down to the baseline: Sprint-3 objects vanish, the baseline tables remain.
    command.downgrade(cfg, _BASELINE)
    insp2 = inspect(create_engine(f"sqlite:///{db}"))
    tables2 = set(insp2.get_table_names())
    assert "roles" not in tables2
    assert "seat_grants" not in tables2
    assert "labels" not in tables2
    assert "projects" in tables2
    assert "status" not in {c["name"] for c in insp2.get_columns("projects")}
    insp2.bind.dispose()

    # And all the way back to an empty schema.
    command.downgrade(cfg, "base")
    insp3 = inspect(create_engine(f"sqlite:///{db}"))
    assert "projects" not in set(insp3.get_table_names())
    insp3.bind.dispose()
