"""spec001 đợt 6: drive deadline + the recovery ladder table, with a backfill

Two additions and one backfill.

`tasks.drive_expires_at` is the second half of a drive: the kind was added in đợt 2, but a
kind alone cannot answer the only question the stall sweep asks — *is this still
believable?* Kept on the task row, beside `drive`, so that sweep is one indexed scan of one
table. It runs forever over every open task; a join there would be a join on the hot path.

`task_push_reasons` holds the recovery ladder: which rung a stuck task is on, how much of
the Level-1 budget the current cause has spent, when the next attempt is due. Unique on
task, because two ladders on one task would let two sweeps each believe they were the one
escalating and the patron would be asked twice about the same thing. Deliberately *not*
holding the drive's kind — that stays on `tasks.drive`, so no field lives in two places.

**Backfill.** Đợt 2 added `drive` nullable and left every existing task NULL, with a note
that đợt 6 would fill it in. That day is today, and a NULL drive on a live task is exactly
what the new sweep reads as *dropped* — so shipping this without a backfill would raise a
stall alarm on every open task in every project at once, on the first tick after upgrade.

The fill is deliberately coarse, and coarse in the safe direction. It can see the task row
and nothing else — not runs, not wakes, not inbox items, none of which it can join to
reliably across two engines — so it assigns the one drive each status *implies* and gives
it a short deadline instead of guessing an exact one:

  - *blocked*      → waiting on another task; no clock (the blocker has a row of its own)
  - *in_review*    → waiting on a decision; no clock (the reminder ladder chases it)
  - *todo*, *in_progress* → a wake is presumed booked, expiring one sweep interval out

That last line is the one that matters, and it is a **deliberate short grace, not a
claim**. If a wake really is pending, the use cases will refresh the drive well before it
lapses. If nothing is pending — if the task truly was dropped before the upgrade — the
drive expires within minutes and the alarm rings then, on a running service, one task at a
time, instead of all of them in the first second. FR-058 is still honoured; it is honoured
a few minutes late, in exchange for an upgrade that does not look like a total outage.

Revises: d7b3e9c2a840
Create Date: 2026-08-06
"""

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = 'a5d2c9f7e134'
down_revision: Union[str, Sequence[str], None] = 'd7b3e9c2a840'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# How long a backfilled drive is believed. One stall-sweep interval plus a margin: long
# enough that a healthy task's use case refreshes it first, short enough that a genuinely
# dropped task is reported the same minute rather than the same week.
_BACKFILL_GRACE_MINUTES = 5


def upgrade() -> None:
    with op.batch_alter_table('tasks') as batch:
        batch.add_column(
            sa.Column('drive_expires_at', sa.DateTime(timezone=True), nullable=True)
        )

    op.create_table(
        'task_push_reasons',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('task_id', sa.Uuid(), nullable=False),
        sa.Column('ref', sa.Text(), nullable=True),
        sa.Column('level', sa.Integer(), nullable=False, server_default=sa.text('0')),
        sa.Column('attempts', sa.Integer(), nullable=False, server_default=sa.text('0')),
        # How many times the Level-2 handover was attempted and did not reach the
        # Leader. Separate from `attempts`, which counts Level-1 tries and is what the
        # patron's dossier reports as "tried this many times" — folding the two together
        # would make that number claim work that never happened.
        sa.Column(
            'handover_attempts', sa.Integer(), nullable=False, server_default=sa.text('0')
        ),
        sa.Column('cause', sa.Text(), nullable=True),
        sa.Column('last_attempt_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('next_retry_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['task_id'], ['tasks.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(
        'ix_task_push_reasons_task_id', 'task_push_reasons', ['task_id'], unique=True
    )
    op.create_index('ix_task_push_reasons_level', 'task_push_reasons', ['level'])

    # ── the backfill (see the module docstring) ──────────────────────────────────
    # Written as three plain UPDATEs rather than one CASE so each rule reads as the
    # sentence it is, and so a later change to one status cannot silently reshuffle the
    # others. Only rows with no drive are touched: đợt 2 and đợt 3 already set a few
    # (a rejected review books a wake), and those are better answers than any guess here.
    op.execute(
        """
        UPDATE tasks
           SET drive = 'blocked_by_task'
         WHERE drive IS NULL AND status = 'blocked'
        """
    )
    op.execute(
        """
        UPDATE tasks
           SET drive = 'waiting_patron'
         WHERE drive IS NULL AND status = 'in_review'
        """
    )
    # The short-grace case. `drive_expires_at` is set for these and only these, because
    # they are the only two the fill is guessing about — the two above are waits that end
    # on an event, and giving them a clock would invent a second alarm for something
    # already watched.
    op.execute(
        f"""
        UPDATE tasks
           SET drive = 'wake_scheduled',
               drive_expires_at = CURRENT_TIMESTAMP
                                + INTERVAL '{_BACKFILL_GRACE_MINUTES} minutes'
         WHERE drive IS NULL AND status IN ('todo', 'in_progress')
        """
        if op.get_bind().dialect.name == 'postgresql'
        else f"""
        UPDATE tasks
           SET drive = 'wake_scheduled',
               drive_expires_at = datetime('now', '+{_BACKFILL_GRACE_MINUTES} minutes')
         WHERE drive IS NULL AND status IN ('todo', 'in_progress')
        """
    )


def downgrade() -> None:
    op.drop_index('ix_task_push_reasons_level', table_name='task_push_reasons')
    op.drop_index('ix_task_push_reasons_task_id', table_name='task_push_reasons')
    op.drop_table('task_push_reasons')
    with op.batch_alter_table('tasks') as batch:
        batch.drop_column('drive_expires_at')
    # The drives filled in above are deliberately *not* unset. They are as true after a
    # downgrade as before it, and blanking them would hand the next upgrade a board of
    # NULLs to guess at all over again.
