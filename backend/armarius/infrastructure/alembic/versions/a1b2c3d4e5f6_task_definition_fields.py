"""task definition fields: priority, due_date, definition_of_done (#82)

Revision ID: a1b2c3d4e5f6
Revises: f1a2b3c4d5e6
Create Date: 2026-07-17 00:00:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "a1b2c3d4e5f6"
down_revision = "f1a2b3c4d5e6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # The Task entity always carried priority/due_date/definition_of_done, but they were
    # ephemeral — no columns, so a manually-created task lost everything but title/description.
    # Persist them so the patron's full task definition survives a reload (#82).
    op.add_column(
        "tasks",
        sa.Column("priority", sa.String(length=20), nullable=False, server_default="medium"),
    )
    op.add_column(
        "tasks",
        sa.Column("due_date", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "tasks",
        sa.Column("definition_of_done", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("tasks", "definition_of_done")
    op.drop_column("tasks", "due_date")
    op.drop_column("tasks", "priority")
