"""spec001 dot 3: seat granter + task approvals + per-patron auto-approval

Three moves (spec 001, task T087):

1. **`seat_grants.granted_by_user_id`** — which patron put an agent in a seat (FR-034).
   This is what decides who must sign for that agent's output. Recorded at grant time from
   now on; never inferred afterwards.

2. **`task_approvals`** — one row per signature (FR-033). Append-only, with a `round` so a
   signature given for a rejected deliverable cannot close the reworked one.

3. **`project_auto_approvals`** — the "stop asking me" switch, keyed by the *(project,
   patron)* pair (FR-036). Every project has exactly one patron today, so the pair looks
   like waste; a project-level flag would lose whose switch it was, and that is not
   recoverable once rows exist.

**Backfill is a guess, and it is labelled as one.** Existing seats predate the column, so
there is no record of who granted them; they are filled with the workspace owner. Within
the current one-patron-per-project scope that guess happens to be correct — but it is
still a guess, and nothing should come to depend on it. Seats granted from now on carry
the real value.

Downgrade drops both tables and the column. Signatures disappear with them, which is
correct: they were never anywhere else.

Revision ID: a9d4c7f2b8e1
Revises: f4c8e2b6a1d3
Create Date: 2026-08-03 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a9d4c7f2b8e1'
down_revision: Union[str, Sequence[str], None] = 'f4c8e2b6a1d3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _backfill_seat_granter() -> None:
    """Guess the granter of pre-existing seats as the workspace owner.

    True today (one patron per project) and clearly wrong the day that changes — hence the
    note above and the fact that nothing reads this value as authoritative history.
    """
    op.get_bind().execute(
        sa.text(
            "UPDATE seat_grants SET granted_by_user_id = ("
            "  SELECT w.owner_user_id FROM projects p"
            "  JOIN workspaces w ON w.id = p.workspace_id"
            "  WHERE p.id = seat_grants.project_id"
            ") WHERE granted_by_user_id IS NULL"
        )
    )


def upgrade() -> None:
    with op.batch_alter_table('seat_grants') as batch:
        batch.add_column(
            sa.Column('granted_by_user_id', sa.String(length=200), nullable=True)
        )
    op.create_index(
        'ix_seat_grants_granted_by_user_id', 'seat_grants', ['granted_by_user_id']
    )
    _backfill_seat_granter()

    op.create_table(
        'task_approvals',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('task_id', sa.Uuid(), nullable=False),
        sa.Column('round', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('signer_kind', sa.String(length=20), nullable=False, server_default='leader'),
        sa.Column('signer_marius_id', sa.Uuid(), nullable=True),
        sa.Column('signer_user_id', sa.String(length=200), nullable=True),
        sa.Column('result', sa.String(length=20), nullable=False, server_default='approve'),
        sa.Column('reason', sa.Text(), nullable=True),
        sa.Column('is_auto', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('signed_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['task_id'], ['tasks.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_task_approvals_task_id', 'task_approvals', ['task_id'])
    op.create_index(
        'ix_task_approvals_task_round', 'task_approvals', ['task_id', 'round', 'signed_at']
    )

    op.create_table(
        'project_auto_approvals',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('project_id', sa.Uuid(), nullable=False),
        sa.Column('user_id', sa.String(length=200), nullable=False),
        sa.Column('enabled', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['project_id'], ['projects.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('project_id', 'user_id', name='uq_auto_approval_project_user'),
    )
    op.create_index(
        'ix_project_auto_approvals_project_id', 'project_auto_approvals', ['project_id']
    )
    op.create_index(
        'ix_project_auto_approvals_user_id', 'project_auto_approvals', ['user_id']
    )


def downgrade() -> None:
    op.drop_index('ix_project_auto_approvals_user_id', table_name='project_auto_approvals')
    op.drop_index('ix_project_auto_approvals_project_id', table_name='project_auto_approvals')
    op.drop_table('project_auto_approvals')
    op.drop_index('ix_task_approvals_task_round', table_name='task_approvals')
    op.drop_index('ix_task_approvals_task_id', table_name='task_approvals')
    op.drop_table('task_approvals')
    op.drop_index('ix_seat_grants_granted_by_user_id', table_name='seat_grants')
    with op.batch_alter_table('seat_grants') as batch:
        batch.drop_column('granted_by_user_id')
