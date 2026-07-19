"""task_dependencies: persist blocked_by edges for the dependency-gate (#91)

Revision ID: d1a7c2e4b6f8
Revises: c9e5f3a7b1d4
Create Date: 2026-07-19 00:00:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "d1a7c2e4b6f8"
down_revision = "c9e5f3a7b1d4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # The TaskDependency entity + domain dependency-gate existed but had no storage,
    # so the gate was never enforced end-to-end. This table persists the `blocked_by`
    # edges (unique per pair) that the application layer now reads to compute
    # `deps_satisfied`. Pure DDL — no backfill (a fresh DB has no edges).
    op.create_table(
        "task_dependencies",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "task_id", sa.Uuid(), sa.ForeignKey("tasks.id"), nullable=False, index=True
        ),
        sa.Column(
            "blocks_task_id",
            sa.Uuid(),
            sa.ForeignKey("tasks.id"),
            nullable=False,
            index=True,
        ),
        sa.UniqueConstraint(
            "task_id", "blocks_task_id", name="uq_task_dependency_pair"
        ),
    )


def downgrade() -> None:
    op.drop_table("task_dependencies")
