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

import pytest
from sqlalchemy import create_engine, inspect, text

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


def _columns_the_models_declare_but_the_migrations_never_build(engine) -> list[str]:
    inspector = inspect(engine)
    missing: list[str] = []
    for table in Base.metadata.tables.values():
        if not inspector.has_table(table.name):
            missing.append(f"{table.name} (entire table)")
            continue
        present = {c["name"] for c in inspector.get_columns(table.name)}
        missing += [
            f"{table.name}.{c.name}" for c in table.columns if c.name not in present
        ]
    return missing


def test_a_brand_new_machine_reaches_head_on_the_engine_it_deploys_on() -> None:
    """Cùng phép đối chiếu, nhưng trên **Postgres** — thứ máy thật chạy.

    Bài trên chạy trên SQLite, và SQLite bỏ qua gần hết những thứ Postgres bắt bẻ: kiểu cột
    nó không có, ràng buộc nó không kiểm, `ALTER` nó lặng lẽ cho qua. Một migration chỉ gãy
    trên Postgres vẫn để bài ấy xanh — mà đó đúng là lúc `docker compose up` chết trên một
    máy mới, và không ai chạy migration lẻ để phát hiện.

    Nên: một database rỗng thật, `alembic upgrade head` qua đúng đường `docker-entrypoint.sh`
    đi, rồi soi lại từng cột.
    """
    url = os.environ.get("TEST_DATABASE_URL", "").strip()
    if not url:
        pytest.skip("TEST_DATABASE_URL is not set — nothing real to migrate.")
    database = url.rsplit("/", 1)[-1].split("?", 1)[0]
    assert database.endswith("_test"), (
        f"TEST_DATABASE_URL points at {database!r}, and this test empties it. "
        "Point it at a database whose name ends in `_test`."
    )

    sync_url = url.replace("+asyncpg", "+psycopg")
    engine = create_engine(sync_url)
    try:
        # Rỗng nghĩa là rỗng: cả bảng lẫn dấu revision, đúng như một máy chưa từng chạy.
        with engine.begin() as conn:
            conn.execute(text("DROP SCHEMA public CASCADE"))
            conn.execute(text("CREATE SCHEMA public"))

        run = subprocess.run(  # noqa: S603 - fixed argv, test-only
            [sys.executable, "-m", "alembic", "upgrade", "head"],
            cwd=BACKEND_ROOT,
            env=os.environ | {"DATABASE_URL": sync_url},
            capture_output=True,
            text=True,
            timeout=300,
        )
        assert run.returncode == 0, run.stderr or run.stdout

        missing = _columns_the_models_declare_but_the_migrations_never_build(engine)
        assert not missing, (
            "một máy mới sẽ dựng lên thiếu những cột này: " + ", ".join(sorted(missing))
        )
    finally:
        engine.dispose()
