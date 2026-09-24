"""spec002 — the patron's direct conversation with one agent (FR-007p).

One row per agent, the same shape as the project chat's table minus the project: the
transcript, the turn-taking state, and the run currently carrying a turn. Plain UUID ref to the
agent with no FK, which is how every other chat table is keyed; the rows are cleared
explicitly wherever an agent or a workspace is removed.

Going down drops the table and the conversations in it. Nothing else reads them.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "a3f6c1e8d2b9"
down_revision = "c1d8e5f37b04"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "agent_conversations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("marius_id", sa.Uuid(), nullable=False),
        sa.Column("transcript", sa.JSON(), nullable=False),
        sa.Column("state", sa.String(length=20), server_default="idle", nullable=False),
        sa.Column("driving_run_id", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_agent_conversations")),
    )
    with op.batch_alter_table("agent_conversations", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_agent_conversations_marius_id"), ["marius_id"], unique=True
        )
        batch_op.create_index(
            batch_op.f("ix_agent_conversations_driving_run_id"), ["driving_run_id"]
        )


def downgrade() -> None:
    with op.batch_alter_table("agent_conversations", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_agent_conversations_driving_run_id"))
        batch_op.drop_index(batch_op.f("ix_agent_conversations_marius_id"))
    op.drop_table("agent_conversations")
