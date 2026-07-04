"""sprint8 workspace agent pointer (issue #32 — the host seat lives on the workspace)

PR #35 added `workspaces.workspace_agent_id` to the model without this migration, so
the composed stack (which migrates ONLY through `alembic upgrade head` on boot) kept
serving 500s on every workspaces query (issue #38).

Revision ID: b7e3a1c5d9f0
Revises: e8c4f1a9d3b2
Create Date: 2026-07-04 04:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b7e3a1c5d9f0'
down_revision: Union[str, Sequence[str], None] = 'e8c4f1a9d3b2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Plain UUID, no FK — a workspaces→mariuses FK would be circular
    # (mariuses.workspace_id already points back here). Matches the model.
    op.add_column(
        'workspaces', sa.Column('workspace_agent_id', sa.Uuid(), nullable=True)
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('workspaces', 'workspace_agent_id')
