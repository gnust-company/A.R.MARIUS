"""task identifier: human-readable code {KEY}-{seq} (#89)

Revision ID: b8d4e2a1c3f7
Revises: a1b2c3d4e5f6
Create Date: 2026-07-19 00:00:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "b8d4e2a1c3f7"
down_revision = "a1b2c3d4e5f6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # The Task entity always carried an `identifier` field, but it was never persisted
    # (no column) and never generated (always empty). Add the column + its index; the
    # follow-up migration c9e5f3a7b1d4 adds the project KEY + counter that fill it.
    op.add_column(
        "tasks",
        sa.Column("identifier", sa.String(length=32), nullable=True),
    )
    op.create_index("ix_tasks_identifier", "tasks", ["identifier"])


def downgrade() -> None:
    op.drop_index("ix_tasks_identifier", table_name="tasks")
    op.drop_column("tasks", "identifier")
