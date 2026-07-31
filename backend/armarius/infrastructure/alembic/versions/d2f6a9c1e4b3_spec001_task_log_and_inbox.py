"""spec001 foundation: task change log + patron inbox

Two tables three of the six stories share (spec 001, task T010):
  - ``task_logs``   — append-only history per task (FR-021, FR-039, FR-061, FR-079)
  - ``inbox_items`` — one pending decision addressed to one patron (FR-035)

Indexed for the two hot reads: a task's timeline, and "everything still pending for me".

Revision ID: d2f6a9c1e4b3
Revises: c3f8a2d1e7b9
Create Date: 2026-07-31 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd2f6a9c1e4b3'
down_revision: Union[str, Sequence[str], None] = 'c3f8a2d1e7b9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'task_logs',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('task_id', sa.Uuid(), nullable=False),
        sa.Column('seq', sa.Integer(), nullable=False),
        sa.Column('kind', sa.String(length=40), nullable=False),
        sa.Column('actor_kind', sa.String(length=20), nullable=False),
        sa.Column('actor_marius_id', sa.Uuid(), nullable=True),
        sa.Column('actor_user_id', sa.String(length=200), nullable=True),
        sa.Column('before_value', sa.Text(), nullable=True),
        sa.Column('after_value', sa.Text(), nullable=True),
        sa.Column('reason', sa.Text(), nullable=True),
        sa.Column('detail', sa.JSON(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['task_id'], ['tasks.id'], ),
        sa.PrimaryKeyConstraint('id'),
        # The seq allocator reads MAX(seq) and writes MAX+1; this constraint is what
        # stops two concurrent appends from both committing the same number.
        sa.UniqueConstraint('task_id', 'seq', name='uq_task_log_task_seq'),
    )
    with op.batch_alter_table('task_logs', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_task_logs_task_id'), ['task_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_task_logs_kind'), ['kind'], unique=False)

    op.create_table(
        'inbox_items',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('workspace_id', sa.Uuid(), nullable=False),
        sa.Column('recipient_user_id', sa.String(length=200), nullable=False),
        sa.Column('project_id', sa.Uuid(), nullable=True),
        sa.Column('task_id', sa.Uuid(), nullable=True),
        sa.Column('kind', sa.String(length=40), nullable=False),
        sa.Column('status', sa.String(length=20), nullable=False),
        sa.Column('title', sa.String(length=300), nullable=False),
        sa.Column('body', sa.Text(), nullable=True),
        sa.Column('reminder_tier', sa.Integer(), server_default='0', nullable=False),
        sa.Column('attempt_dossier', sa.JSON(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('last_reminded_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('resolved_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['workspace_id'], ['workspaces.id'], ),
        sa.PrimaryKeyConstraint('id'),
    )
    with op.batch_alter_table('inbox_items', schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f('ix_inbox_items_workspace_id'), ['workspace_id'], unique=False
        )
        batch_op.create_index(
            batch_op.f('ix_inbox_items_recipient_user_id'),
            ['recipient_user_id'],
            unique=False,
        )
        batch_op.create_index(
            batch_op.f('ix_inbox_items_project_id'), ['project_id'], unique=False
        )
        batch_op.create_index(
            batch_op.f('ix_inbox_items_task_id'), ['task_id'], unique=False
        )
        batch_op.create_index(batch_op.f('ix_inbox_items_kind'), ['kind'], unique=False)
        batch_op.create_index(
            batch_op.f('ix_inbox_items_created_at'), ['created_at'], unique=False
        )
        # The hot read: everything still pending for one patron.
        batch_op.create_index(
            'ix_inbox_items_recipient_status',
            ['recipient_user_id', 'status'],
            unique=False,
        )


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('inbox_items', schema=None) as batch_op:
        batch_op.drop_index('ix_inbox_items_recipient_status')
        batch_op.drop_index(batch_op.f('ix_inbox_items_created_at'))
        batch_op.drop_index(batch_op.f('ix_inbox_items_kind'))
        batch_op.drop_index(batch_op.f('ix_inbox_items_task_id'))
        batch_op.drop_index(batch_op.f('ix_inbox_items_project_id'))
        batch_op.drop_index(batch_op.f('ix_inbox_items_recipient_user_id'))
        batch_op.drop_index(batch_op.f('ix_inbox_items_workspace_id'))
    op.drop_table('inbox_items')

    with op.batch_alter_table('task_logs', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_task_logs_kind'))
        batch_op.drop_index(batch_op.f('ix_task_logs_task_id'))
    op.drop_table('task_logs')
