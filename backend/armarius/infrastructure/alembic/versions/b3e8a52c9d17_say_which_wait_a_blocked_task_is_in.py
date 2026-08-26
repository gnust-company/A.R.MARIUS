"""spec002: record which shape of drive #5 a task is in

`blocked_by_task` covers two different waits. One is *behind another task*: somebody else's
work has to land first, and the answer is to go and chase it. The other is *behind a queue
with no room*: the task is ready, and every machine it could run on is busy — the answer is
to leave it alone, because nothing is wrong (FR-008a, FR-008e).

The rule has told them apart since spec 001; the difference was computed and then dropped on
the floor, because the task carried only the drive's *kind*. So the board could not show a
patron the one state FR-008b asks for by name — *waiting for a free machine* — and had to
render both waits as the same sentence.

A code, not a sentence: the same fact is put in front of a patron in their own language and
handed to an agent in English (Constitution VII).

No backfill. The value is derived from live runs and live dependency edges, and both move
between now and the next time anyone looks; guessing one here would put an answer on the
board that nothing checked. The next refresh of each task writes the real one, and until then
the column reads as *not settled yet*, which is honest.

Revision ID: b3e8a52c9d17
Revises: a1b7d3f95c28
Create Date: 2026-08-26

"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "b3e8a52c9d17"
down_revision: str | None = "a1b7d3f95c28"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.add_column("tasks", sa.Column("drive_code", sa.String(length=30), nullable=True))


def downgrade() -> None:
    op.drop_column("tasks", "drive_code")
