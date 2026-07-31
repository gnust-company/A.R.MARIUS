"""spec001 dot 2: task scope/drive/stall columns + acceptance criteria table

Three moves (spec 001, task T067):

1. **Four columns on `tasks`** — `plan_item_id` (what makes a task in scope, FR-027),
   `drive` (what is moving it, FR-056), and `stalled` + `stalled_reason` (the alarm that
   the system dropped it, FR-058). Existing rows get `stalled = false` and a NULL drive:
   Story 6 owns filling drives in, and a NULL drive on a live task is exactly the thing
   its watchdog is meant to notice.

2. **`checklist_items`** — the acceptance-criteria table (FR-019). The entity existed in
   the domain since the first sprint but had no table and no repository; it was never
   wired to anything. It is the yardstick now.

3. **Old prose becomes one criterion.** Every task with a non-empty `definition_of_done`
   gets a single *unrated* criterion carrying that text verbatim. Deliberately **not**
   split on newlines or bullets: a wrong guess would silently invent acceptance criteria
   nobody wrote, and a human re-reading one paragraph is cheaper than a human hunting for
   the criterion a parser fabricated. The original text is left in place as history.

Downgrade drops the columns and the table; the migrated criteria disappear with it, which
is correct — the prose they were copied from was never removed.

Revision ID: f4c8e2b6a1d3
Revises: e7b3d1f5a2c8
Create Date: 2026-07-31 00:00:00.000000

"""
import uuid
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f4c8e2b6a1d3'
down_revision: Union[str, Sequence[str], None] = 'e7b3d1f5a2c8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _seed_criteria_from_prose() -> None:
    """Copy each task's free-text definition of done into one unrated criterion."""
    bind = op.get_bind()
    rows = bind.execute(
        sa.text(
            "SELECT id, definition_of_done FROM tasks "
            "WHERE definition_of_done IS NOT NULL AND definition_of_done <> ''"
        )
    ).fetchall()
    for task_id, prose in rows:
        text = (prose or '').strip()
        if not text:
            continue
        bind.execute(
            sa.text(
                "INSERT INTO checklist_items "
                "(id, task_id, text, done, order_index, result, evidence_artifact_id) "
                "VALUES (:id, :task_id, :text, :done, 0, 'unrated', NULL)"
            ),
            {
                "id": str(uuid.uuid4()),
                "task_id": str(task_id),
                "text": text,
                "done": False,
            },
        )


def upgrade() -> None:
    with op.batch_alter_table('tasks') as batch:
        batch.add_column(sa.Column('plan_item_id', sa.Uuid(), nullable=True))
        batch.add_column(sa.Column('drive', sa.String(length=20), nullable=True))
        batch.add_column(
            sa.Column(
                'stalled', sa.Boolean(), nullable=False, server_default=sa.false()
            )
        )
        batch.add_column(sa.Column('stalled_reason', sa.Text(), nullable=True))
    op.create_index('ix_tasks_plan_item_id', 'tasks', ['plan_item_id'])
    op.create_index('ix_tasks_drive', 'tasks', ['drive'])
    op.create_index('ix_tasks_stalled', 'tasks', ['stalled'])

    op.create_table(
        'checklist_items',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('task_id', sa.Uuid(), nullable=False),
        sa.Column('text', sa.Text(), nullable=False, server_default=''),
        sa.Column('done', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('order_index', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('result', sa.String(length=20), nullable=False, server_default='unrated'),
        sa.Column('evidence_artifact_id', sa.Uuid(), nullable=True),
        sa.ForeignKeyConstraint(['task_id'], ['tasks.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_checklist_items_task_id', 'checklist_items', ['task_id'])

    _seed_criteria_from_prose()


def downgrade() -> None:
    op.drop_index('ix_checklist_items_task_id', table_name='checklist_items')
    op.drop_table('checklist_items')
    op.drop_index('ix_tasks_stalled', table_name='tasks')
    op.drop_index('ix_tasks_drive', table_name='tasks')
    op.drop_index('ix_tasks_plan_item_id', table_name='tasks')
    with op.batch_alter_table('tasks') as batch:
        batch.drop_column('stalled_reason')
        batch.drop_column('stalled')
        batch.drop_column('drive')
        batch.drop_column('plan_item_id')
