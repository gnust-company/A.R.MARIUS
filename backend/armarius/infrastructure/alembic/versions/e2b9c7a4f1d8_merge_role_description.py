"""merge role description: dồn responsibilities → description, drop responsibilities (#93)

Revision ID: e2b9c7a4f1d8
Revises: d1a7c2e4b6f8
Create Date: 2026-07-19 00:00:00.000000

Role từng mang HAI trường mô tả (`description` cho mọi role + `responsibilities`
"nhiệm vụ riêng của Leader"). `responsibilities` là mã chết — không khung nhìn hay
prompt nào đọc — nên gộp về MỘT trường `description` (#93). Đây là migration có
backfill dữ liệu (ngoại lệ có chủ đích như c9e5f3a7b1d4): dồn chữ cũ trong
`responsibilities` sang `description` khi `description` còn trống, rồi drop cột. Trên
CSDL sạch (parity test) không có hàng ⇒ backfill no-op, chỉ còn thao tác DDL.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "e2b9c7a4f1d8"
down_revision = "d1a7c2e4b6f8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Không mất chữ người dùng đã nhập: dồn responsibilities → description khi description trống.
    op.execute(
        sa.text(
            "UPDATE roles SET description = responsibilities "
            "WHERE (description IS NULL OR description = '') "
            "AND responsibilities IS NOT NULL AND responsibilities <> ''"
        )
    )
    op.drop_column("roles", "responsibilities")


def downgrade() -> None:
    # Chỉ khôi phục được cột rỗng — dữ liệu đã dồn vào description không tách ngược lại.
    op.add_column(
        "roles",
        sa.Column("responsibilities", sa.Text(), nullable=False, server_default=""),
    )
