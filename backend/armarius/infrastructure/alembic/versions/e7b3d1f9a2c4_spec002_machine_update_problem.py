"""spec002 — a machine says why its daemon is not keeping itself current (FR-008n, revised
2026-10-28).

One nullable column on `machines`: the code the daemon sent on its last beat. Null for every
existing row, which is what a daemon too old to say anything reads as.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "e7b3d1f9a2c4"
down_revision = "d4e9a2c7f1b3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("machines", schema=None) as batch_op:
        batch_op.add_column(sa.Column("update_problem", sa.String(length=64), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("machines", schema=None) as batch_op:
        batch_op.drop_column("update_problem")
