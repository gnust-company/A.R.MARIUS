"""project leader conversations (Chat-with-Leader, #82)

Revision ID: f1a2b3c4d5e6
Revises: b7e3a1c5d9f0
Create Date: 2026-07-17 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f1a2b3c4d5e6'
down_revision: Union[str, Sequence[str], None] = 'b7e3a1c5d9f0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('project_leader_conversations',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('project_id', sa.Uuid(), nullable=True),
    sa.Column('leader_marius_id', sa.Uuid(), nullable=True),
    sa.Column('session_params', sa.JSON(), nullable=False),
    sa.Column('transcript', sa.JSON(), nullable=False),
    sa.Column('state', sa.String(length=20), server_default='idle', nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('project_leader_conversations', schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f('ix_project_leader_conversations_project_id'),
            ['project_id'], unique=True
        )
        batch_op.create_index(
            batch_op.f('ix_project_leader_conversations_leader_marius_id'),
            ['leader_marius_id'], unique=False
        )
        batch_op.create_index(
            batch_op.f('ix_project_leader_conversations_state'), ['state'], unique=False
        )


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('project_leader_conversations', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_project_leader_conversations_state'))
        batch_op.drop_index(batch_op.f('ix_project_leader_conversations_leader_marius_id'))
        batch_op.drop_index(batch_op.f('ix_project_leader_conversations_project_id'))

    op.drop_table('project_leader_conversations')
