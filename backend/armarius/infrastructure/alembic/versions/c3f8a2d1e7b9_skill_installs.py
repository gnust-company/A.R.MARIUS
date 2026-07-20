"""add mariuses.skill_installs — post-invite skill install state (#74 / #105)

The post-invite install loop tracks each pushed skill's state per agent
(slug → pending|installed|failed). The model gained the column; the composed stack
migrates ONLY through `alembic upgrade head`, so it needs this migration or every
mariuses query 500s (cf. issue #38).

Revision ID: c3f8a2d1e7b9
Revises: a1c4e8b2d6f9
Create Date: 2026-07-20 08:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c3f8a2d1e7b9'
down_revision: Union[str, Sequence[str], None] = 'a1c4e8b2d6f9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # NOT NULL to mirror the model; server_default backfills existing rows with an empty map.
    op.add_column(
        'mariuses',
        sa.Column(
            'skill_installs', sa.JSON(), nullable=False, server_default=sa.text("'{}'")
        ),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('mariuses', 'skill_installs')
