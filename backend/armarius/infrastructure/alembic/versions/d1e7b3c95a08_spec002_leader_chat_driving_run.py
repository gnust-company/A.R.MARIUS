"""Chat với Trưởng dự án cũng đi từng lượt chạy một (T048c).

Cùng một lý do đã thêm `onboarding_sessions.driving_run_id` ở c5d81f0a72e4, và cùng một hình
dạng: một lượt nói của Trưởng dự án nay có thể **diễn ra trên máy người dùng**, nơi tiến trình
này không ngồi đợi được. Tin lượt ấy kết thúc về sau, qua cửa của daemon, và thứ duy nhất nó
mang theo là tên lượt chạy — nên cuộc trò chuyện phải tra được **từ** lượt chạy.

Hỏi ngược lại — dự án này đang mở cuộc nào — không dùng được: mỗi dự án chỉ có một cuộc trò
chuyện, nhưng nó sống mãi qua nhiều lượt, nên câu trả lời ấy không phân biệt được lượt vừa xong
với lượt trước đó. `state` nói *có một lượt đang chạy*; cột này nói *lượt nào*.

Revision ID: d1e7b3c95a08
Revises: c5d81f0a72e4
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "d1e7b3c95a08"
down_revision: str | Sequence[str] | None = "c5d81f0a72e4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "project_leader_conversations",
        sa.Column("driving_run_id", sa.Uuid(), nullable=True),
    )
    op.create_index(
        "ix_project_leader_conversations_driving_run_id",
        "project_leader_conversations",
        ["driving_run_id"],
    )


def downgrade() -> None:
    # The index first, then the column it is on — dropping a column out from under its own
    # index is refused outright by some engines and silently tolerated by others.
    op.drop_index(
        "ix_project_leader_conversations_driving_run_id",
        table_name="project_leader_conversations",
    )
    op.drop_column("project_leader_conversations", "driving_run_id")
