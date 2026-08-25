"""spec002: an agent's instructions, its description, and one name per workspace

Three changes, all of them consequences of the same decision (FR-007g):

* `instructions` — what the agent is told to be. It goes down with every run (FR-007i),
  which is what makes it impossible for an agent to drift away from it or for a compressed
  session to lose it.
* `description` — what the team calls it among themselves. It never reaches the agent
  (FR-007j); a line written for people would otherwise quietly become an instruction.
* a unique `(workspace_id, name)` — two agents answering to the same name in one workspace
  leaves nobody, patron or Leader, able to say which one they meant (FR-007h).

Both columns land NOT NULL with an empty default rather than nullable. Empty instructions
and absent instructions are the same thing to every reader of this column, and a nullable
column would ask each of them to decide that again.

The unique constraint is added last, after the columns, because it can fail on data that is
already there: a workspace that has two agents sharing a name predates the rule. There is no
such data yet (spec Assumptions), and the migration is deliberately allowed to fail loudly
rather than to rename anything on somebody's behalf.

Revision ID: e4c9f7b21a63
Revises: d8a3b6c41e57
Create Date: 2026-08-25 00:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "e4c9f7b21a63"
down_revision: str | None = "d8a3b6c41e57"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "mariuses",
        sa.Column("instructions", sa.Text(), nullable=False, server_default=""),
    )
    op.add_column(
        "mariuses",
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
    )
    # Batch mode, because the suite runs these migrations on SQLite and SQLite cannot ALTER a
    # constraint into an existing table — it has to copy the table and move it. On Postgres,
    # where this actually ships, batch mode issues the plain ALTER.
    with op.batch_alter_table("mariuses") as batch:
        batch.create_unique_constraint(
            "uq_mariuses_workspace_name", ["workspace_id", "name"]
        )


def downgrade() -> None:
    with op.batch_alter_table("mariuses") as batch:
        batch.drop_constraint("uq_mariuses_workspace_name", type_="unique")
    op.drop_column("mariuses", "description")
    op.drop_column("mariuses", "instructions")
