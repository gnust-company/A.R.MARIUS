"""spec002: drop mariuses.skill_installs

The column recorded a per-skill install state — pushed, awaiting the agent's confirmation,
confirmed — for a loop that no longer exists. Skills are written onto the machine that runs
the agent, as part of the work packet, every single run (FR-011b). *Granted* and *present on
disk* stopped being two facts that could disagree, so there is nothing left to reconcile and
nothing left for the agent to confirm (FR-011c).

Left behind, the column would keep answering a question nobody asks any more, with values
last written by a road that has been taken out — which is the worst kind of record: one that
looks current.

Revision ID: d5b1c8e73f04
Revises: c7f2a9d41b68
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "d5b1c8e73f04"
down_revision: str | Sequence[str] | None = "c7f2a9d41b68"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_column("mariuses", "skill_installs")


def downgrade() -> None:
    op.add_column(
        "mariuses",
        sa.Column("skill_installs", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
    )
