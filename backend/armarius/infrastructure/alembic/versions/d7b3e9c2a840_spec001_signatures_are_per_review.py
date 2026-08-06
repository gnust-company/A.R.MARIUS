"""spec001: a signature belongs to one review, not to a round number

Replaces `task_approvals.round` with `task_approvals.superseded`.

The round number was a *derived* value stamped onto each row — "how many times has this
task been sent back, plus one" — and every reader had to derive the same number again to
know which signatures were still current. Three readers derived it, one derived it
differently, and a task pulled out of review by hand derived nothing at all: it kept its
Leader signature and closed the reworked deliverable on a signature given for the draft
before it.

`superseded` is read, not computed. It is set on every signature a task carries at the
moment the task goes back to being worked on.

**Backfill.** Every pre-existing signature is retired except on tasks that are already
closed. Deliberately blunt, and chosen over the precise version after the precise version
turned out to be wrong.

The precise version asked "has this task left review?" and spared anything still sitting
in *in_review*. It missed the shape in the middle: a task rejected once, reworked,
re-submitted, and in review at upgrade time. Its old **rejection** row survived as a live
signature, and the closing gate vetoes on any live rejection — so that task could never
reach *done* again, while `missing_signatures` stayed empty and the orchestrator reported
nothing. Stuck, and silent, which is the exact failure this whole feature exists to
prevent.

So: a task waiting on its second signature has to collect the first one again. That is one
round of annoyance, once, at upgrade — and it heals itself, because the orchestrator sees
a missing Leader signature and wakes the right party. The alternative failure is a task
wedged for good. A migration runs once, unattended, on data nobody can inspect afterwards;
it is the worst possible place to bet on a clever predicate, so this one fails **shut**
rather than **stuck**.

Tasks already in *done* or *cancelled* keep their signatures: the review that closed them
is still the review that stands, and reopening one retires them anyway (FR-041a).

Revises: c4f1a8b3d2e7
Create Date: 2026-08-06
"""

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = 'd7b3e9c2a840'
down_revision: Union[str, Sequence[str], None] = 'c4f1a8b3d2e7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'task_approvals',
        sa.Column(
            'superseded',
            sa.Boolean(),
            nullable=False,
            server_default=sa.text('false'),
        ),
    )
    # Retire every signature except on tasks that are already closed. See the module
    # docstring for why this is blunt on purpose: the invariant it buys is that no task
    # comes out of the upgrade carrying a rejection that still counts, and a live
    # rejection is a task that can never close again without anything saying so.
    op.execute(
        """
        UPDATE task_approvals
           SET superseded = true
         WHERE task_id IN (
               SELECT id FROM tasks
                WHERE status NOT IN ('done', 'cancelled')
         )
        """
    )
    op.drop_index('ix_task_approvals_task_round', table_name='task_approvals')
    op.create_index(
        'ix_task_approvals_task_signed',
        'task_approvals',
        ['task_id', 'signed_at'],
    )
    op.drop_column('task_approvals', 'round')


def downgrade() -> None:
    # The round number cannot be recovered from a flag, so every row comes back as round
    # one. That is the honest reconstruction: the old column's information is gone the
    # moment it is dropped, and pretending otherwise would put invented numbers in a
    # signature ledger.
    op.add_column(
        'task_approvals',
        sa.Column(
            'round',
            sa.Integer(),
            nullable=False,
            server_default=sa.text('1'),
        ),
    )
    op.drop_index('ix_task_approvals_task_signed', table_name='task_approvals')
    op.create_index(
        'ix_task_approvals_task_round',
        'task_approvals',
        ['task_id', 'round', 'signed_at'],
    )
    op.drop_column('task_approvals', 'superseded')
