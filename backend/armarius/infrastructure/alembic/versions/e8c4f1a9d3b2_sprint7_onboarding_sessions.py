"""sprint7 onboarding sessions (agent-assisted project setup)

Revision ID: e8c4f1a9d3b2
Revises: d5b1f0a2c9e7
Create Date: 2026-07-01 11:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e8c4f1a9d3b2'
down_revision: Union[str, Sequence[str], None] = 'd5b1f0a2c9e7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('onboarding_sessions',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('workspace_id', sa.Uuid(), nullable=True),
    sa.Column('status', sa.String(length=20), server_default='open', nullable=False),
    sa.Column('transcript', sa.JSON(), nullable=False),
    sa.Column('collected', sa.JSON(), nullable=False),
    sa.Column('created_project_id', sa.Uuid(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('onboarding_sessions', schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f('ix_onboarding_sessions_workspace_id'),
            ['workspace_id'], unique=False
        )
        batch_op.create_index(
            batch_op.f('ix_onboarding_sessions_status'), ['status'], unique=False
        )


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('onboarding_sessions', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_onboarding_sessions_status'))
        batch_op.drop_index(batch_op.f('ix_onboarding_sessions_workspace_id'))

    op.drop_table('onboarding_sessions')
