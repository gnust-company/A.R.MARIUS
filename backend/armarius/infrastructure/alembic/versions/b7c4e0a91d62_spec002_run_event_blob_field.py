"""Nói ra toàn văn ấy là toàn văn của **khoá nào** (T099, FR-049).

`run_event_blobs` đã có từ khi dựng lược đồ daemon, nhưng nó chỉ trỏ về sự kiện chứ không nói
phần chữ nó giữ là phần chữ của trường nào. Suy ra được — mỗi loại sự kiện có đúng một trường
dài — nhưng suy ra nghĩa là mọi chỗ đọc phải chép lại cùng một bảng ánh xạ, và cái thứ hai chép
sai sẽ mở ra một trường không có ở đó.

`server_default ''` cho những hàng viết trước cột này. Hôm nay chưa có hàng nào — bảng dựng rồi
mà chưa có gì ghi vào — nhưng một cột NOT NULL không mặc định là một migration hỏng trên bất kỳ
cơ sở dữ liệu nào đã chạy thật.

Revision ID: b7c4e0a91d62
Revises: e4a71c9d3b52
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b7c4e0a91d62"
down_revision: str | Sequence[str] | None = "e4a71c9d3b52"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "run_event_blobs",
        sa.Column("field", sa.String(length=40), nullable=False, server_default=""),
    )


def downgrade() -> None:
    op.drop_column("run_event_blobs", "field")
