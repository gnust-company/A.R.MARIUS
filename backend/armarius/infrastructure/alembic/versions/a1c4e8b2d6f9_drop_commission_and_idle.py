"""drop commission + backfill liveness idle→online (GĐ-2 C+D)

Revision ID: a1c4e8b2d6f9
Revises: f3a1b8c5d2e7
Create Date: 2026-07-19

Hai việc dọn miền đánh thức, gộp một file:

1. **D — gỡ Commission** (đã bị Chat với Leader #82 thay thế hoàn toàn): xoá bảng
   ``commission_sessions``. Toàn bộ thực thể/use case/endpoint/FE dead code gỡ ở cùng đợt.
2. **C — ``Liveness.IDLE`` → dùng lại ``ONLINE``**: trạng thái "rảnh giữa các lượt" giờ là
   ``ONLINE`` (sau lượt, ``last_seen_at`` vừa = tín hiệu). Backfill các hàng cũ đang lưu
   ``liveness='idle'`` thành ``'online'`` để không còn giá trị mồ côi sau khi enum bỏ IDLE.

Đây là di trú **data + DDL** (lần thứ hai có backfill, sau #93), cô lập trong một file.
Downgrade chỉ tái tạo **cấu trúc** bảng commission (best-effort); backfill ``idle→online``
**không đảo ngược được** — không còn ngữ nghĩa nào cho ``idle`` sau khi enum đã gỡ value.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy import text

# revision identifiers, used by Alembic.
revision = "a1c4e8b2d6f9"
down_revision = "f3a1b8c5d2e7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # C — backfill before the enum drops the value: any legacy row still 'idle' becomes
    # 'online' (free-between-turns now means ONLINE, the watchdog maintains it via gateway).
    op.get_bind().execute(
        text("UPDATE mariuses SET liveness = 'online' WHERE liveness = 'idle'")
    )
    # D — the commission chat table is gone (replaced by project Leader chat, #82).
    op.drop_table("commission_sessions")


def downgrade() -> None:
    # D — recreate the commission_sessions structure (best-effort; no data to restore —
    # the subsystem is dead). Mirrors d5b1f0a2c9e7_sprint5_commission_sessions.
    op.create_table(
        "commission_sessions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=True),
        sa.Column("leader_marius_id", sa.Uuid(), nullable=True),
        sa.Column("task_id", sa.Uuid(), nullable=True),
        sa.Column("session_params", sa.JSON(), nullable=True),
        sa.Column("transcript", sa.JSON(), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=True),
        sa.Column("leader_state", sa.String(length=20), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_commission_sessions_project_id"),
        "commission_sessions",
        ["project_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_commission_sessions_leader_marius_id"),
        "commission_sessions",
        ["leader_marius_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_commission_sessions_task_id"),
        "commission_sessions",
        ["task_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_commission_sessions_status"),
        "commission_sessions",
        ["status"],
        unique=False,
    )
    # C — the idle→online backfill is NOT reversible: 'idle' no longer exists in the enum,
    # so there is no meaningful value to restore. Intentionally a no-op here.
