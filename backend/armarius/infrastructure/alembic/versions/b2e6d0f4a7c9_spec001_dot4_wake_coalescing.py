"""spec001 dot 4: coalescing moves from process memory into the schema

FR-050 says at most **one** pending wake and **one** live run per *(agent, task)* pair.
Until now that was a dictionary inside the wake engine, which meant it held only as long
as one process kept running — a restart forgot every pair it was holding, and a second
worker never knew about the first. Two partial unique indexes make it an actual invariant.

**Partial on purpose.** Settled rows fall outside the index, so a pair frees up as soon as
its wake is done. A full unique index would say "this agent may be woken for this task
exactly once, ever".

**Duplicates are cleaned up before the indexes go on**, because rows that predate them can
easily violate them — the old engine had no way to prevent a restart from leaving two.
The rule for choosing which row survives is *keep the newest*: an older pending wake whose
process is long gone is precisely the wedge this migration exists to clear, and the newest
row is the one whose cause is still relevant. Losers are marked `failed` rather than
deleted — they are real history, and the audit trail of why an agent was woken is worth
more than a tidy table.

Rows with a NULL `task_id` (project-level runs) are untouched: NULL never equals NULL, so
they cannot collide in either index.

Downgrade drops both indexes. It does not restore the rows it retired — their content is
still there, only their status changed, so nothing is actually lost.

Revision ID: b2e6d0f4a7c9
Revises: a9d4c7f2b8e1
Create Date: 2026-08-03 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b2e6d0f4a7c9'
down_revision: Union[str, Sequence[str], None] = 'a9d4c7f2b8e1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_PENDING_WAKE = "status IN ('queued','dispatched')"
_ACTIVE_RUN = "status IN ('queued','running')"


def _retire_duplicate_pending_wakes() -> None:
    """Leave one pending wake per pair — the newest — and mark the rest failed."""
    op.get_bind().execute(
        sa.text(
            "UPDATE wakeup_requests SET status = 'failed' "
            "WHERE status IN ('queued','dispatched') "
            "  AND marius_id IS NOT NULL AND task_id IS NOT NULL "
            "  AND id NOT IN ("
            "    SELECT keep.id FROM ("
            "      SELECT id, marius_id, task_id, created_at FROM wakeup_requests"
            "      WHERE status IN ('queued','dispatched')"
            "        AND marius_id IS NOT NULL AND task_id IS NOT NULL"
            "    ) keep"
            "    WHERE NOT EXISTS ("
            "      SELECT 1 FROM wakeup_requests newer"
            "      WHERE newer.status IN ('queued','dispatched')"
            "        AND newer.marius_id = keep.marius_id"
            "        AND newer.task_id = keep.task_id"
            "        AND (newer.created_at > keep.created_at"
            "             OR (newer.created_at = keep.created_at AND newer.id > keep.id))"
            "    )"
            "  )"
        )
    )


def _retire_duplicate_active_runs() -> None:
    """Same rule for runs: keep the newest live one, stop the rest.

    A run retired here is one no process is driving any more — the container that owned it
    is gone. `stopped` says that honestly; leaving it `running` would keep the pair wedged
    and would also lie to the liveness watchdog.
    """
    op.get_bind().execute(
        sa.text(
            "UPDATE runs SET status = 'stopped', "
            "  error = COALESCE(error, 'lượt chạy mồ côi, dọn khi đặt ràng buộc gộp') "
            "WHERE status IN ('queued','running') "
            "  AND marius_id IS NOT NULL AND task_id IS NOT NULL "
            "  AND id NOT IN ("
            "    SELECT keep.id FROM ("
            "      SELECT id, marius_id, task_id, created_at FROM runs"
            "      WHERE status IN ('queued','running')"
            "        AND marius_id IS NOT NULL AND task_id IS NOT NULL"
            "    ) keep"
            "    WHERE NOT EXISTS ("
            "      SELECT 1 FROM runs newer"
            "      WHERE newer.status IN ('queued','running')"
            "        AND newer.marius_id = keep.marius_id"
            "        AND newer.task_id = keep.task_id"
            "        AND (newer.created_at > keep.created_at"
            "             OR (newer.created_at = keep.created_at AND newer.id > keep.id))"
            "    )"
            "  )"
        )
    )


def upgrade() -> None:
    _retire_duplicate_pending_wakes()
    _retire_duplicate_active_runs()

    op.create_index(
        'uq_wakeup_pending_per_agent_task',
        'wakeup_requests',
        ['marius_id', 'task_id'],
        unique=True,
        sqlite_where=sa.text(_PENDING_WAKE),
        postgresql_where=sa.text(_PENDING_WAKE),
    )
    op.create_index(
        'uq_run_active_per_agent_task',
        'runs',
        ['marius_id', 'task_id'],
        unique=True,
        sqlite_where=sa.text(_ACTIVE_RUN),
        postgresql_where=sa.text(_ACTIVE_RUN),
    )


def downgrade() -> None:
    op.drop_index('uq_run_active_per_agent_task', table_name='runs')
    op.drop_index('uq_wakeup_pending_per_agent_task', table_name='wakeup_requests')
