"""Buổi phỏng vấn là một lượt chạy, và agent thôi giữ token riêng (T048a, T039d).

Hai nửa của cùng một việc, nên cùng một migration.

**Thêm** `onboarding_sessions.driving_run_id`: buổi hỏi–đáp dựng đội đi từng lượt một, mỗi lượt
là một lượt chạy cấp workspace (FR-040c). Lượt chạy ấy diễn ra ở nơi tiến trình này không nhìn
thấy, và tin nó kết thúc về sau, chỉ kèm theo tên lượt chạy — nên buổi phỏng vấn phải tra được
**từ** lượt chạy. Hỏi ngược lại — workspace này đang mở buổi nào — trả lời sai đúng lúc người
chủ huỷ rồi mở lại: lượt của buổi cũ sẽ bị đọc thành lượt của buổi mới.

**Bỏ** `mariuses.agent_token`, `mariuses.invite_status`, `mariuses.approved_at`: hệ thống chỉ có
hai loại token — của máy và của lượt chạy (FR-014a). Token thứ ba từng sống bằng hai lối
onboarding, thứ duy nhất trong 22 lối `/agent/*` không thuộc lượt chạy nào; nửa trên của
migration này lấy đi chỗ dựa cuối cùng ấy. Vòng đời lời mời đi theo nó: mốc duy nhất nó đánh dấu
là lúc token được đúc, nên không còn token thì các trạng thái ấy không mô tả gì nữa.

Chiều `downgrade` dựng lại cột chứ **không** dựng lại token: giá trị cũ đã mất cùng cột, và đúc
lại một chuỗi mới ở đây sẽ là phát cho mỗi agent một chìa khoá không ai yêu cầu.

Revision ID: c5d81f0a72e4
Revises: b7c4e0a91d62
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c5d81f0a72e4"
down_revision: str | Sequence[str] | None = "b7c4e0a91d62"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "onboarding_sessions",
        sa.Column("driving_run_id", sa.Uuid(), nullable=True),
    )
    op.create_index(
        "ix_onboarding_sessions_driving_run_id",
        "onboarding_sessions",
        ["driving_run_id"],
    )

    # The index goes before the column it is on: dropping a column out from under its own
    # index is refused outright by some engines and silently tolerated by others, and a
    # migration that only runs on one of them is a migration that has not been written.
    with op.batch_alter_table("mariuses") as batch_op:
        batch_op.drop_index("ix_mariuses_agent_token")
        batch_op.drop_column("agent_token")
        batch_op.drop_column("invite_status")
        batch_op.drop_column("approved_at")


def downgrade() -> None:
    with op.batch_alter_table("mariuses") as batch_op:
        batch_op.add_column(
            sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True)
        )
        batch_op.add_column(
            sa.Column(
                "invite_status",
                sa.String(length=20),
                nullable=False,
                server_default="approved",
            )
        )
        batch_op.add_column(sa.Column("agent_token", sa.String(length=120), nullable=True))
        batch_op.create_index("ix_mariuses_agent_token", ["agent_token"], unique=True)

    op.drop_index("ix_onboarding_sessions_driving_run_id", "onboarding_sessions")
    op.drop_column("onboarding_sessions", "driving_run_id")
