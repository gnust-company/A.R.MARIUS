"""Trạng thái ba bước đầu tiên, trên chính người dùng (T004, FR-100, FR-104).

Trong browser thì không được: ba bước ấy là một lần cho **một tài khoản**, không phải một lần
cho mỗi máy, nên một người đăng ký ở laptop rồi mở lại ở điện thoại không được bị hỏi lần hai.

`onboarded_at` có giá trị là toàn bộ nghĩa của *đã xong*. Một con số bước không nói được điều
đó — bước 3 vừa là *đang đứng ở bước cuối* vừa là *đã xong bước cuối* — còn thêm một cờ boolean
cạnh con số là thêm hai thứ có thể nói ngược nhau.

**Người dùng đã có được đánh dấu là xong.** Họ đã dùng sản phẩm rồi; để mặc định rỗng là sáng
mai mọi người đang dùng đều bị đẩy vào một luồng dành cho người mới. Đây là nửa quan trọng của
migration này, không phải phần dọn dẹp thêm.

Revision ID: f3a91c2d0e57
Revises: d1e7b3c95a08
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "f3a91c2d0e57"
down_revision: str | Sequence[str] | None = "d1e7b3c95a08"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("onboarding_step", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "users",
        sa.Column("onboarded_at", sa.DateTime(timezone=True), nullable=True),
    )
    # Mọi tài khoản đã tồn tại: coi như đã đi xong. Dùng `created_at` của chính họ chứ không
    # phải `now()` — nói *người này xong ba bước lúc chạy migration* là ghi vào cơ sở dữ liệu
    # một điều không xảy ra.
    op.execute(
        "UPDATE users SET onboarded_at = COALESCE(created_at, CURRENT_TIMESTAMP), "
        "onboarding_step = 3 WHERE onboarded_at IS NULL"
    )


def downgrade() -> None:
    op.drop_column("users", "onboarded_at")
    op.drop_column("users", "onboarding_step")
