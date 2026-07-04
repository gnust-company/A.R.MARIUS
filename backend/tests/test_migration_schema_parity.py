"""`alembic upgrade head` must produce every table and column the ORM models declare.

The composed stack migrates ONLY through Alembic (docker-entrypoint.sh) — init_db's
create_all never runs there — so a model change shipped without a migration leaves the
live schema behind and the API 500s at first touch (issue #38, workspace_agent_id).
This test runs the real migration chain against a fresh database and diffs it
column-by-column against Base.metadata, failing with the exact columns that still
need a migration.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from sqlalchemy import create_engine, inspect

from armarius.infrastructure.database.models import Base

BACKEND_ROOT = Path(__file__).resolve().parents[1]


def test_alembic_head_covers_the_model_metadata(tmp_path: Path) -> None:
    db_file = tmp_path / "parity.db"
    # A subprocess (not alembic's Python API) so the app settings are rebuilt from
    # this DATABASE_URL — the in-process `settings` singleton is already cached.
    run = subprocess.run(  # noqa: S603 - fixed argv, test-only
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=BACKEND_ROOT,
        env=os.environ | {"DATABASE_URL": f"sqlite+aiosqlite:///{db_file}"},
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert run.returncode == 0, run.stderr or run.stdout

    engine = create_engine(f"sqlite:///{db_file}")
    try:
        inspector = inspect(engine)
        missing: list[str] = []
        for table in Base.metadata.tables.values():
            if not inspector.has_table(table.name):
                missing.append(f"{table.name} (entire table)")
                continue
            present = {c["name"] for c in inspector.get_columns(table.name)}
            missing += [
                f"{table.name}.{c.name}"
                for c in table.columns
                if c.name not in present
            ]
        assert not missing, (
            "schema drift — these model columns are unreachable via `alembic upgrade "
            "head`; write a migration for: " + ", ".join(sorted(missing))
        )
    finally:
        engine.dispose()
