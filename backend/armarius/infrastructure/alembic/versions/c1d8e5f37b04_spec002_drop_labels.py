"""spec002 — bỏ bảng nhãn, vì không có gì dùng nó.

*Người chủ hỏi 2026-09-08: "Nhãn là cái đéo gì?"* — và câu trả lời là: không là gì cả. Đo lại
toàn bộ bề mặt của nó thì thấy một bảng, hai cửa (`GET`/`POST`), một hàm phía giao diện **không
ai gọi**, và **không một chỗ nào gắn nhãn vào bất cứ thứ gì**: thực thể đầu việc không có trường
nhãn, schema đầu việc không có, không màn hình nào có. Nó là mẩu sót lại từ hợp đồng gốc §5.4,
chưa từng được nối vào đâu.

Giữ một cửa tạo được mà không đọc lại được ở đâu thì tệ hơn không có: nó là một lời hứa trên
giấy tờ API mà sản phẩm không giữ. Khi nào có màn hình cần nhãn thì làm lại, cùng chỗ gắn nhãn.

Đường xuống dựng lại đúng bảng cũ (bản `c3a7d9e1b2f4`), nên đi xuống là về đúng schema trước đó
— chỉ không có dữ liệu, mà bảng này thì chưa có cửa nào ghi vào ngoài một cửa `POST` không màn
hình nào gọi.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "c1d8e5f37b04"
down_revision = "b7e4d2a91c68"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("labels", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_labels_workspace_id"))
    op.drop_table("labels")


def downgrade() -> None:
    op.create_table(
        "labels",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("color", sa.String(length=20), server_default="", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("labels", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_labels_workspace_id"), ["workspace_id"], unique=False
        )
