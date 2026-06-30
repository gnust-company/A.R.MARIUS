"""sprint4 labels (workspace-scoped task tags)

Revision ID: c3a7d9e1b2f4
Revises: 468899ef9a27
Create Date: 2026-06-30 10:15:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c3a7d9e1b2f4'
down_revision: Union[str, Sequence[str], None] = '468899ef9a27'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('labels',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('workspace_id', sa.Uuid(), nullable=False),
    sa.Column('name', sa.String(length=120), nullable=False),
    sa.Column('color', sa.String(length=20), server_default='', nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=True),
    sa.ForeignKeyConstraint(['workspace_id'], ['workspaces.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('labels', schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f('ix_labels_workspace_id'), ['workspace_id'], unique=False
        )


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('labels', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_labels_workspace_id'))

    op.drop_table('labels')
