"""sprint5 commission sessions (leader-mediated task shaping)

Revision ID: d5b1f0a2c9e7
Revises: c3a7d9e1b2f4
Create Date: 2026-07-01 09:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd5b1f0a2c9e7'
down_revision: Union[str, Sequence[str], None] = 'c3a7d9e1b2f4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('commission_sessions',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('project_id', sa.Uuid(), nullable=True),
    sa.Column('leader_marius_id', sa.Uuid(), nullable=True),
    sa.Column('task_id', sa.Uuid(), nullable=True),
    sa.Column('session_params', sa.JSON(), nullable=False),
    sa.Column('transcript', sa.JSON(), nullable=False),
    sa.Column('status', sa.String(length=20), server_default='open', nullable=False),
    sa.Column('leader_state', sa.String(length=20), server_default='thinking', nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('commission_sessions', schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f('ix_commission_sessions_project_id'), ['project_id'], unique=False
        )
        batch_op.create_index(
            batch_op.f('ix_commission_sessions_leader_marius_id'),
            ['leader_marius_id'], unique=False
        )
        batch_op.create_index(
            batch_op.f('ix_commission_sessions_task_id'), ['task_id'], unique=False
        )
        batch_op.create_index(
            batch_op.f('ix_commission_sessions_status'), ['status'], unique=False
        )


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('commission_sessions', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_commission_sessions_status'))
        batch_op.drop_index(batch_op.f('ix_commission_sessions_task_id'))
        batch_op.drop_index(batch_op.f('ix_commission_sessions_leader_marius_id'))
        batch_op.drop_index(batch_op.f('ix_commission_sessions_project_id'))

    op.drop_table('commission_sessions')
