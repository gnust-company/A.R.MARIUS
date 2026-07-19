"""project key + per-project task sequence counter (#89)

Revision ID: c9e5f3a7b1d4
Revises: b8d4e2a1c3f7
Create Date: 2026-07-19 00:00:00.000000

Adds two columns to ``projects``:

- ``key`` — short uppercase code unique per workspace; the KEY in task identifiers
  ``{KEY}-{seq}`` (JIRA-style). Backfilled for existing projects from their name.
- ``next_task_seq`` — monotonic per-project counter, atomically bumped by
  ``ProjectRepository.allocate_task_number`` (``UPDATE … RETURNING``) so concurrent
  task creates never share a number and numbers are never reused.

This is the repo's first data-backfill migration (prior ones are DDL-only). The
suggestion helper is duplicated inline (not imported) so the migration stays frozen.
On a fresh DB the backfill is a no-op (no projects) — the schema-parity test still
passes.
"""

from __future__ import annotations

import unicodedata
from typing import Any

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "c9e5f3a7b1d4"
down_revision = "b8d4e2a1c3f7"
branch_labels = None
depends_on = None


def _suggest_key(name: str) -> str:
    """Inline copy of domain.services.project_key.suggest_project_key (frozen for migration)."""
    normalized = (name or "").replace("đ", "d").replace("Đ", "d")
    decomposed = unicodedata.normalize("NFKD", normalized)
    letters = [c for c in decomposed if c.isascii() and c.isalpha()]
    key = "".join(letters[:4]).upper() or "PROJ"
    return key if len(key) >= 2 else key + "X" * (2 - len(key))


def _backfill(conn: Any) -> None:
    rows = conn.execute(
        sa.text("SELECT id, workspace_id, name, key FROM projects ORDER BY created_at")
    ).mappings().all()

    # Phase 1 — give every project a key unique within its workspace.
    used: dict[Any, set[str]] = {}
    for row in rows:
        workspace_id = row["workspace_id"]
        used.setdefault(workspace_id, set())
        existing = row["key"]
        if existing:
            key = existing
        else:
            base = _suggest_key(row["name"])
            key, i = base, 2
            while key in used[workspace_id]:
                key = f"{base}{i}"
                i += 1
        used[workspace_id].add(key)
        conn.execute(
            sa.text("UPDATE projects SET key = :k WHERE id = :id"),
            {"k": key, "id": row["id"]},
        )

    # Phase 2 — number existing tasks per project and prime the counter.
    projects = conn.execute(sa.text("SELECT id, key FROM projects")).mappings().all()
    for proj in projects:
        tasks = conn.execute(
            sa.text("SELECT id FROM tasks WHERE project_id = :p ORDER BY created_at"),
            {"p": proj["id"]},
        ).mappings().all()
        for index, task in enumerate(tasks, start=1):
            conn.execute(
                sa.text("UPDATE tasks SET identifier = :id WHERE id = :tid"),
                {"id": f"{proj['key']}-{index}", "tid": task["id"]},
            )
        conn.execute(
            sa.text("UPDATE projects SET next_task_seq = :n WHERE id = :p"),
            {"n": len(tasks) + 1, "p": proj["id"]},
        )


def upgrade() -> None:
    op.add_column("projects", sa.Column("key", sa.String(length=10), nullable=True))
    op.add_column(
        "projects",
        sa.Column("next_task_seq", sa.Integer(), nullable=False, server_default="1"),
    )
    _backfill(op.get_bind())
    # SQLite cannot ALTER … ADD CONSTRAINT — batch mode copy-and-moves the table; on
    # Postgres batch is a no-op wrapper, so this is portable.
    with op.batch_alter_table("projects") as batch_op:
        batch_op.create_unique_constraint("uq_project_ws_key", ["workspace_id", "key"])


def downgrade() -> None:
    with op.batch_alter_table("projects") as batch_op:
        batch_op.drop_constraint("uq_project_ws_key", type_="unique")
    op.drop_column("projects", "next_task_seq")
    op.drop_column("projects", "key")
