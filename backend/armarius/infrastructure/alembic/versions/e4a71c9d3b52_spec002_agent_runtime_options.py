"""Chỗ giữ thứ người dùng chọn cho từng agent, theo thứ chỗ làm khai ra (T039g, FR-007k).

Một cột chứ không một cột mỗi thiết lập. Bộ thiết lập là câu trả lời của **tool**, không phải
của ta: Claude Code nhận model và mức nghĩ, Codex có thêm một hạng dịch vụ. Dựng hai cột đúng
tên bây giờ là để hạng thứ ba không có chỗ đứng, và mua thêm một lần migration vào đúng ngày có
người hỏi tới nó.

**Cột mang tên khác lớp nghiệp vụ, và đó là cố ý.** Ở đây là `runtime_options` vì hạ tầng và
dây nói *runtime*; `domain/` với `application/` gọi cùng thứ ấy là `placement_options` vì Điều
III cấm hai lớp đó biết việc chạy ở đâu. Chỗ dịch tên nằm đúng một chỗ mỗi chiều: đọc ở
`mappers.py`, ghi ở `repositories.py`.

`NOT NULL DEFAULT '{}'` chứ không nullable: với mọi chỗ đọc thì *chưa chọn gì* và *không có gì
để chọn* là một, và một cột nullable chỉ bắt từng chỗ đọc tự quyết lại chuyện đó.

Revision ID: e4a71c9d3b52
Revises: d5b1c8e73f04
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "e4a71c9d3b52"
down_revision: str | Sequence[str] | None = "d5b1c8e73f04"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "mariuses",
        sa.Column("runtime_options", sa.JSON(), nullable=False, server_default="{}"),
    )


def downgrade() -> None:
    op.drop_column("mariuses", "runtime_options")
