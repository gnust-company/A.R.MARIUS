"""spec001 T193: keep the wake causes as data beside their English rendering

The line that says *why this agent was woken* has two readers who do not read the same
language — the agent, whose packet is English end to end, and the patron, who reads the very
same line on the agent screen in whichever language they picked. A sentence written once at
wake time can only serve one of them (Constitution VII).

So each wake now records the causes as ``[{"code": ..., "params": {...}}]`` and each reader
words them itself. The existing ``reason`` / ``trigger_detail`` columns keep the English
rendering: it is what the packet carries, and it is the only thing rows written before today
have to show.

Both columns are nullable with no backfill, which is the honest thing here — the old rows
hold a finished sentence and no code, and inventing a code from a sentence would be guessing.
The screen falls back to the stored sentence whenever the list is empty, so old runs read
exactly as they did before.

Revises: b4e7f1a9c206
Create Date: 2026-08-16
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "c7a1f3d05b48"
down_revision = "b4e7f1a9c206"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("wakeup_requests", sa.Column("causes", sa.JSON(), nullable=True))
    op.add_column("runs", sa.Column("trigger_causes", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("runs", "trigger_causes")
    op.drop_column("wakeup_requests", "causes")
