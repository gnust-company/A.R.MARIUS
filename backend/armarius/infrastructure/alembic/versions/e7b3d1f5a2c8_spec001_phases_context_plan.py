"""spec001 dot 1: five project phases + context/plan tables + drop two dead flags

Three moves (spec 001, task T036):

1. **Phases.** `setup → active → archived` becomes the five-phase lifecycle
   `setup → planning → operating ⇄ maintaining → closed`. Existing rows are remapped:
   `active → operating`, `archived → closed`. Projects already in `setup` stay put; a
   project mid-flight keeps its meaning, only its name changes.

2. **Three tables** — `project_contexts`, `plans`, `plan_items`.

3. **Two flags out of `projects.settings`.** `require_approval_for_done` was declared and
   never read — dead weight that made the "no deciding for you" rule look ambiguous.
   `yolo_mode` is superseded by "inside an approved plan item" (FR-027); the code that
   still reads it lands in Đợt 2 (T062), and until then a missing key reads as `False`,
   which is exactly what its default already was — so removing it now changes nothing.

The settings rewrite runs in Python rather than as JSON SQL so it behaves identically on
SQLite (tests, parity) and PostgreSQL (the composed stack).

Revision ID: e7b3d1f5a2c8
Revises: d2f6a9c1e4b3
Create Date: 2026-07-31 00:00:00.000000

"""
import json
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e7b3d1f5a2c8'
down_revision: Union[str, Sequence[str], None] = 'd2f6a9c1e4b3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_DEAD_FLAGS = ('require_approval_for_done', 'yolo_mode')


def _rewrite_settings(drop_keys: Sequence[str]) -> None:
    """Strip keys from every project's settings JSON, in Python for portability."""
    bind = op.get_bind()
    rows = bind.execute(sa.text("SELECT id, settings FROM projects")).fetchall()
    for row in rows:
        raw = row[1]
        if raw is None:
            continue
        settings = json.loads(raw) if isinstance(raw, str) else dict(raw)
        if not isinstance(settings, dict):
            continue
        if not any(k in settings for k in drop_keys):
            continue
        for key in drop_keys:
            settings.pop(key, None)
        bind.execute(
            sa.text("UPDATE projects SET settings = :s WHERE id = :i"),
            {"s": json.dumps(settings), "i": row[0]},
        )


def upgrade() -> None:
    """Upgrade schema."""
    op.execute("UPDATE projects SET status = 'operating' WHERE status = 'active'")
    op.execute("UPDATE projects SET status = 'closed' WHERE status = 'archived'")
    _rewrite_settings(_DEAD_FLAGS)

    op.create_table(
        'project_contexts',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('project_id', sa.Uuid(), nullable=False),
        sa.Column('version', sa.Integer(), nullable=False),
        sa.Column('objective', sa.Text(), nullable=False),
        sa.Column('background', sa.Text(), nullable=False),
        sa.Column('constraints', sa.Text(), nullable=False),
        sa.Column('scope', sa.Text(), nullable=False),
        sa.Column('principles', sa.Text(), nullable=False),
        sa.Column('approval_status', sa.String(length=20), nullable=False),
        sa.Column('approved_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('approved_by_user_id', sa.String(length=200), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('project_id', 'version', name='uq_project_context_version'),
    )
    with op.batch_alter_table('project_contexts', schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f('ix_project_contexts_project_id'), ['project_id'], unique=False
        )
        batch_op.create_index(
            batch_op.f('ix_project_contexts_approval_status'),
            ['approval_status'],
            unique=False,
        )

    op.create_table(
        'plans',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('project_id', sa.Uuid(), nullable=False),
        sa.Column('version', sa.Integer(), nullable=False),
        sa.Column('summary', sa.Text(), nullable=False),
        sa.Column('risks', sa.Text(), nullable=False),
        sa.Column('milestones', sa.Text(), nullable=False),
        sa.Column('status', sa.String(length=20), nullable=False),
        sa.Column('patron_note', sa.Text(), nullable=True),
        sa.Column('submitted_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('decided_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('decided_by_user_id', sa.String(length=200), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('project_id', 'version', name='uq_plan_version'),
    )
    with op.batch_alter_table('plans', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_plans_project_id'), ['project_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_plans_status'), ['status'], unique=False)

    op.create_table(
        'plan_items',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('plan_id', sa.Uuid(), nullable=False),
        sa.Column('title', sa.String(length=300), nullable=False),
        sa.Column('description', sa.Text(), nullable=False),
        sa.Column('order_index', sa.Integer(), nullable=False),
        sa.Column('depends_on', sa.JSON(), nullable=False),
        sa.Column('definition_of_done', sa.Text(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['plan_id'], ['plans.id'], ),
        sa.PrimaryKeyConstraint('id'),
    )
    with op.batch_alter_table('plan_items', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_plan_items_plan_id'), ['plan_id'], unique=False)


def downgrade() -> None:
    """Downgrade schema.

    The two dead flags are NOT restored — they had no readers, so putting them back would
    only re-create the ambiguity. Phases fold back onto the old three values; `planning`
    collapses to `setup` because a project that never got its plan approved had not
    started work.
    """
    with op.batch_alter_table('plan_items', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_plan_items_plan_id'))
    op.drop_table('plan_items')

    with op.batch_alter_table('plans', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_plans_status'))
        batch_op.drop_index(batch_op.f('ix_plans_project_id'))
    op.drop_table('plans')

    with op.batch_alter_table('project_contexts', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_project_contexts_approval_status'))
        batch_op.drop_index(batch_op.f('ix_project_contexts_project_id'))
    op.drop_table('project_contexts')

    op.execute("UPDATE projects SET status = 'setup' WHERE status = 'planning'")
    op.execute("UPDATE projects SET status = 'active' WHERE status IN ('operating', 'maintaining')")
    op.execute("UPDATE projects SET status = 'archived' WHERE status = 'closed'")
