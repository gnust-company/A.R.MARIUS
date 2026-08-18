"""spec001 T200: the stall verdict is a code, not a Vietnamese sentence

`tasks.stalled_reason` held a finished sentence, written by the sweep in Vietnamese. The
same value is shown on the patron's board, handed to the escalation ladder and put in front
of an agent — and an agent has no interface language to pick from (Constitution VII). So the
column now holds the verdict's **code**; the server renders English for records and agents,
and the screen renders the patron's own language.

Unlike the wake causes in c7a1f3d05b48, a backfill is possible here and is not a guess: the
sweep only ever wrote five distinct sentences, and each maps to exactly one code. Anything
else that ended up in the column becomes the catch-all rather than being left as prose the
screen cannot word.

`task_push_reasons.cause` gets the same treatment. It is the *same verdict*, handed to the
escalation ladder — `stall_watchdog` writes one value into both. Converting only the task
would leave every ladder mid-climb at deploy time holding a sentence, and `stall_text_en`
would quietly degrade it to the catch-all: no crash, but the detail lost on exactly the
tasks that were in trouble when the deploy happened.

Revises: c7a1f3d05b48
Create Date: 2026-08-18
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "d3f7b2a6c1e8"
down_revision = "c7a1f3d05b48"
branch_labels = None
depends_on = None

# Every sentence `stall_reason` could produce, and the code that replaces it. The last of
# them was an f-string over the drive name, so it is matched by prefix.
_SENTENCE_TO_CODE = {
    "việc bị bỏ quên: không ai đang làm, cũng không có lịch gọi ai vào làm": "stall_orphaned",
    "người làm nhận việc rồi tắt tiếng giữa chừng": "stall_run_active",
    "đã gọi người làm nhưng nó chưa từng bắt đầu": "stall_wake_scheduled",
    "gọi lại mấy lần đều không tới được người làm": "stall_waiting_recovery",
    "đang chờ một thứ bên ngoài, quá hạn rồi vẫn chưa thấy": "stall_waiting_external",
}

_CODES = tuple(_SENTENCE_TO_CODE.values()) + ("stall_unknown",)


def _convert(table: sa.TableClause, column: sa.ColumnClause[str]) -> None:
    for sentence, code in _SENTENCE_TO_CODE.items():
        op.execute(table.update().where(column == sentence).values({column.name: code}))
    # Whatever is left is prose from an older build (or the drive-name fallback). The screen
    # can word "we lost track of why"; it cannot word a Vietnamese sentence it has no key
    # for, and showing the raw text to an agent is the thing this change is undoing.
    op.execute(
        table.update()
        .where(column.isnot(None))
        .where(column.notin_(_CODES))
        .values({column.name: "stall_unknown"})
    )


def upgrade() -> None:
    tasks = sa.table("tasks", sa.column("stalled_reason", sa.Text()))
    ladders = sa.table("task_push_reasons", sa.column("cause", sa.Text()))
    _convert(tasks, tasks.c.stalled_reason)
    _convert(ladders, ladders.c.cause)


def _revert(table: sa.TableClause, column: sa.ColumnClause[str]) -> None:
    for sentence, code in _SENTENCE_TO_CODE.items():
        op.execute(table.update().where(column == code).values({column.name: sentence}))
    op.execute(
        table.update().where(column == "stall_unknown").values({column.name: None})
    )


def downgrade() -> None:
    """Back to sentences. The catch-all has no sentence of its own, so it clears."""
    tasks = sa.table("tasks", sa.column("stalled_reason", sa.Text()))
    ladders = sa.table("task_push_reasons", sa.column("cause", sa.Text()))
    _revert(tasks, tasks.c.stalled_reason)
    _revert(ladders, ladders.c.cause)
