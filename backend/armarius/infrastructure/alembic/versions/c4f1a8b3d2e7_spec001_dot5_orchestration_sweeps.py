"""spec001 dot 5: the orchestration cadence leaves a record

Every pass of the orchestration loop writes a row here — including, and especially, the
passes that found nothing. FR-053 says a healthy project's cadence must pass in silence;
a loop that is simply broken produces the same silence. Nothing else in the schema can
tell those two apart, so without this table the feature would be unfalsifiable on a
running service.

The rows are also what make the rhythm honest across a restart. The quiet streak that
earns a project a longer gap, and the ceiling on cadence wakes per hour (FR-055), are both
read back from here rather than held in a counter on a live object — a counter that a
redeploy resets is a ceiling that a redeploy lifts.

Append-only: no updates, no deletes. Reads are always "this project's most recent sweeps,
newest first", which is what the composite index serves.

Revision ID: c4f1a8b3d2e7
Revises: b2e6d0f4a7c9
Create Date: 2026-08-05 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c4f1a8b3d2e7'
down_revision: Union[str, Sequence[str], None] = 'b2e6d0f4a7c9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'orchestration_sweeps',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('project_id', sa.Uuid(), nullable=False),
        sa.Column('swept_at', sa.DateTime(timezone=True), nullable=True),
        # The snags as found, whole. A count alone would leave the board unable to say
        # *what* the last look saw without redoing the look.
        sa.Column('snags', sa.JSON(), nullable=True),
        sa.Column('snag_count', sa.Integer(), nullable=True),
        sa.Column('woke_leader', sa.Boolean(), nullable=True),
        # Why a sweep that found something still stayed quiet — in words, so a reason
        # added later reads as itself rather than as another flag.
        sa.Column('skipped_reason', sa.Text(), nullable=True),
        sa.Column('next_interval_seconds', sa.Integer(), nullable=True),
        # Deadline marks already announced per task, so a warning fires when it is crossed
        # and not on every sweep for the rest of the day (FR-052).
        sa.Column('reported_marks', sa.JSON(), nullable=True),
        sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(
        op.f('ix_orchestration_sweeps_project_id'),
        'orchestration_sweeps',
        ['project_id'],
        unique=False,
    )
    op.create_index(
        'ix_sweep_project_time',
        'orchestration_sweeps',
        ['project_id', 'swept_at'],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index('ix_sweep_project_time', table_name='orchestration_sweeps')
    op.drop_index(
        op.f('ix_orchestration_sweeps_project_id'), table_name='orchestration_sweeps'
    )
    op.drop_table('orchestration_sweeps')
