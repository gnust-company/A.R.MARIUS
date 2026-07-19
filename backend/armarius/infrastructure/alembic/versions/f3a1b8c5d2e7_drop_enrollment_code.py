"""drop enrollment_code (issue #97)

Revision ID: f3a1b8c5d2e7
Revises: e2b9c7a4f1d8
Create Date: 2026-07-19

Gỡ cột ``mariuses.enrollment_code`` — tàn dư từ mô hình enroll-and-wait đã bị thay thế
bởi operator-invite (#63): token được mint ngay tại lúc mời và đẩy qua gateway, không còn
cổng enroll/approve. Trường này chưa bao giờ được gán giá trị cho agent mới và không phơi
ra API. Đây là di trú DDL thuần (drop cột) — không cần backfill vì không có dữ liệu thật.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "f3a1b8c5d2e7"
down_revision = "e2b9c7a4f1d8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_column("mariuses", "enrollment_code")


def downgrade() -> None:
    op.add_column(
        "mariuses",
        sa.Column("enrollment_code", sa.String(length=120), nullable=True),
    )
