"""Nối lại ba nhánh migration đã tách — không nhánh nào thêm gì, chỉ để `head` có một nghĩa.

**Chuỗi migration trên `main` đã tách làm ba từ trước đợt này**, và hậu quả không nhỏ:
`alembic upgrade head` dừng với *"Multiple head revisions are present"*, nên **backend không
khởi động nổi bằng docker compose** — mục `entrypoint` chạy migration trước rồi mới chạy app.

Vì sao không ai thấy: bộ kiểm dựng bảng thẳng từ metadata của SQLAlchemy, không chạy migration.
Nên 1052 bài xanh trên một cơ sở dữ liệu **chưa từng đi qua đường mà máy thật đi**. Bắt được
đúng lúc dựng dịch vụ thật lên để lái màn hình (T039g).

Ba nhánh nối ở đây độc lập nhau — lưới an toàn của đặc tả 001, phòng chat Trưởng dự án, và
nhánh của đặc tả 002 — không nhánh nào đụng bảng của nhánh nào, nên thứ tự giữa chúng không
mang nghĩa gì. Bản gộp này **không có `upgrade` nào**: nó là một mối nối, không phải một thay
đổi lược đồ.

Revision ID: f8c3b0d5a291
Revises: a5d2c9f7e134, f1a2b3c4d5e6, e4a71c9d3b52
"""

from __future__ import annotations

from collections.abc import Sequence

revision: str = "f8c3b0d5a291"
down_revision: str | Sequence[str] | None = (
    "a5d2c9f7e134",
    "f1a2b3c4d5e6",
    "e4a71c9d3b52",
)
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Nothing to do: this revision exists to give `head` a single answer."""


def downgrade() -> None:
    """Nothing to undo, for the same reason."""
