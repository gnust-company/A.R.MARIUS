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

**Backfill.** Existing rows are marked superseded when the task has since left review —
that is, any task not currently in *in_review*, *done* or *cancelled*. Signatures on tasks
sitting in review keep counting, which is what their owners intended when they gave them.

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
    # Retire signatures whose task has already moved on. Anything still in review, done or
    # cancelled keeps them — those are the tasks whose deliverable has not been reworked.
    op.execute(
        """
        UPDATE task_approvals
           SET superseded = true
         WHERE task_id IN (
               SELECT id FROM tasks
                WHERE status NOT IN ('in_review', 'done', 'cancelled')
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
