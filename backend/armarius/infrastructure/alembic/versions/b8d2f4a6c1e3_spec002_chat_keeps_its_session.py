"""spec002 — a chat keeps its agent's own session between turns (FR-040c).

Two columns, one on each side of a turn:

* ``runs.conversation_key`` names the conversation a run carries on when it is not a task's —
  the patron's direct chat with an agent, a project's chat with its Leader. The machine keeps
  that conversation's session under this name, the way it keeps a task's under the task.
* ``wakeup_requests.fresh_prompt`` is the message for a turn that cannot carry the session on:
  the same message with the recent turns written back in.

Both nullable and both empty for every row written before them, which is exactly right: those
runs carried nothing on. Going down drops them.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "b8d2f4a6c1e3"
down_revision = "a3f6c1e8d2b9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("runs", schema=None) as batch_op:
        batch_op.add_column(sa.Column("conversation_key", sa.String(length=120), nullable=True))
    with op.batch_alter_table("wakeup_requests", schema=None) as batch_op:
        batch_op.add_column(sa.Column("fresh_prompt", sa.Text(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("wakeup_requests", schema=None) as batch_op:
        batch_op.drop_column("fresh_prompt")
    with op.batch_alter_table("runs", schema=None) as batch_op:
        batch_op.drop_column("conversation_key")
