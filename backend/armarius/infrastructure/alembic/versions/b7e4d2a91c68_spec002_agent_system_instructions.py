"""spec002 — nửa prompt do sản phẩm viết, tách khỏi nửa của người chủ (FR-007m).

Người chủ nhà của mỗi không gian làm việc sinh ra với một công việc viết bằng tiếng Anh
(FR-115), và tới nay công việc ấy nằm trong `instructions` — đúng cái ô mà từ nay người chủ
sửa được. Để y nguyên thì lần đầu ai đó sửa chỉ dẫn cho Livia của mình là xoá luôn thứ làm
nó thành người chủ nhà.

Nên hàng nào đang giữ **đúng** đoạn chữ của sản phẩm thì đoạn ấy chuyển sang `system_instructions`,
còn `instructions` để trống cho người chủ. So khớp **đúng từng ký tự** chứ không đoán: một
người chủ đã tự viết lại chỉ dẫn cho người chủ nhà của họ thì chữ của họ **không được** chuyển
đi đâu cả, và cũng không được nhân đôi.

Đường xuống gộp hai nửa lại theo đúng thứ tự prompt dựng chúng, nên đi xuống rồi đi lên lại
không mất chữ của ai.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "b7e4d2a91c68"
down_revision = "a8c31f6b90d4"
branch_labels = None
depends_on = None

# Đoạn chữ đúng như `WorkspaceAgentService.HOST_INSTRUCTIONS` lúc migration này được viết.
# Chép vào đây chứ không import: một migration phải đọc được y hệt mười phiên bản sau, còn
# hằng số kia thì được phép đổi.
HOST_INSTRUCTIONS_AT_THIS_REVISION = (
    'You are the host of this workspace. You are the first agent its owner talks to: you greet '
    'them, help them shape their first project, and answer questions about what this workspace '
    'can do. You do not carry project work yourself — other agents are hired for that, and your '
    'job is to help decide what to hire and what to ask for.'
)


def upgrade() -> None:
    op.add_column(
        "mariuses",
        sa.Column(
            "system_instructions",
            sa.Text(),
            nullable=False,
            server_default="",
        ),
    )
    mariuses = sa.table(
        "mariuses",
        sa.column("instructions", sa.Text),
        sa.column("system_instructions", sa.Text),
    )
    op.execute(
        mariuses.update()
        .where(mariuses.c.instructions == HOST_INSTRUCTIONS_AT_THIS_REVISION)
        .values(
            system_instructions=HOST_INSTRUCTIONS_AT_THIS_REVISION,
            instructions="",
        )
    )


def downgrade() -> None:
    # Gộp lại trước khi bỏ cột, và theo đúng thứ tự prompt dựng: nửa sản phẩm trên, nửa người
    # chủ dưới. Bỏ cột trước rồi mới nghĩ tới chữ là mất hẳn công việc của người chủ nhà.
    mariuses = sa.table(
        "mariuses",
        sa.column("instructions", sa.Text),
        sa.column("system_instructions", sa.Text),
    )
    joined = sa.case(
        (
            sa.func.coalesce(mariuses.c.instructions, "") == "",
            mariuses.c.system_instructions,
        ),
        else_=mariuses.c.system_instructions + "\n\n" + mariuses.c.instructions,
    )
    op.execute(
        mariuses.update()
        .where(sa.func.coalesce(mariuses.c.system_instructions, "") != "")
        .values(instructions=joined)
    )
    op.drop_column("mariuses", "system_instructions")
