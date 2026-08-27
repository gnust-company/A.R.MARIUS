"""spec002: one event per (run, seq)

A run's events are numbered on the machine that produced them, in the order the agent
produced them, and sent up in batches. That is what lets a machine keep working without a
round trip per event to agree on the next number — and it is only safe because of this
index: a batch whose reply went missing is simply sent again, and the numbers it carries are
numbers the store already holds, so nothing is written twice (FR-045).

The message an agent was given keeps sequence zero, which is why the numbering above starts
at one. It is the one entry in a run's log written before the agent existed, so it sits
before everything the agent produced, and it leaves the whole of 1..N to the machine.

Revision ID: c7f2a9d41b68
Revises: b3e8a52c9d17
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "c7f2a9d41b68"
down_revision: str | Sequence[str] | None = "b3e8a52c9d17"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Deliberately not tolerant of duplicates. Two rows sharing a number would mean a run
    # whose log cannot be put back in order, and quietly keeping one of them would hide
    # exactly the fault this index exists to make impossible.
    op.create_index(
        "uq_run_events_run_seq",
        "run_events",
        ["run_id", "seq"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("uq_run_events_run_seq", table_name="run_events")
