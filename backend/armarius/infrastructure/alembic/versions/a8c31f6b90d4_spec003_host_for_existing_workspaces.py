"""Không gian làm việc đã tồn tại cũng phải có người chủ nhà (T005, FR-110, FR-113).

Điều khoản nói **mọi** không gian làm việc, không phải mọi không gian làm việc tạo từ mai. Hôm
nay không cái nào có, vì suốt từ issue #63 tới giờ không có đường nào tạo — nên hệ quả đang
sống là: mọi tài khoản hiện có đều không dùng được chế độ dựng dự án bằng hỏi–đáp, và màn tạo dự
án tự tắt chế độ ấy với câu *"set up a Workspace Agent first"* mà không chỉ ra đường nào làm.

Làm bằng SQL chứ không bằng mã ứng dụng, và không làm lúc đăng nhập: đây là việc **một lần** cho
dữ liệu đã có. Nhét nó vào đường đăng nhập là bắt mọi lần đăng nhập về sau trả giá cho một lần
sửa dữ liệu.

Ba thứ cẩn thận:

- Chỉ chạm không gian làm việc **chưa có** người chủ nhà — không theo `workspace_agent_id`, mà
  theo cả vai `Workspace Agent`, vì không gian làm việc trước #32 nhận nhau bằng vai.
- `adapter_type` để rỗng: đó chính là *chưa được đặt vào runtime nào*. Đoán một giá trị là tầng
  dữ liệu tự đặt tên một runtime.
- Tên `Livia` có thể đã bị dùng. Ở đây tránh bằng cách bỏ qua đúng những không gian làm việc ấy
  — chúng sẽ được `provide_host` xử lý (nó lách tên) lần tới có ai gọi tới. Một migration không
  phải chỗ viết vòng lặp tìm tên còn trống.

Revision ID: a8c31f6b90d4
Revises: f3a91c2d0e57
"""

from __future__ import annotations

from collections.abc import Sequence
from uuid import UUID, uuid4

import sqlalchemy as sa
from alembic import op

revision: str = "a8c31f6b90d4"
down_revision: str | Sequence[str] | None = "f3a91c2d0e57"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

HOST_NAME = "Livia"

# Giữ khớp với HOST_INSTRUCTIONS ở application/use_cases/workspace_agent.py. Hai bản của cùng
# một câu là chuyện của migration: một migration đọc mã ứng dụng là một migration đổi nghĩa theo
# lần deploy, còn nó thì phải nói đúng một điều mãi mãi.
HOST_INSTRUCTIONS = (
    "You are the host of this workspace. You are the first agent its owner talks to: you "
    "greet them, help them shape their first project, and answer questions about what this "
    "workspace can do. You do not carry project work yourself — other agents are hired for "
    "that, and your job is to help decide what to hire and what to ask for."
)


def upgrade() -> None:
    """Một hàng người chủ nhà cho mỗi không gian làm việc chưa có.

    Làm bằng Python chứ không bằng một câu `INSERT … SELECT`: id phải sinh ở đây thì mới trỏ
    được `workspace_agent_id` vào đúng hàng vừa tạo, và `gen_random_uuid()` là hàm của
    Postgres — bộ kiểm chạy migration trên SQLite, nên một câu lệnh chỉ đúng ở một dialect là
    một migration chỉ chạy ở một nơi. *Tìm ra bằng phép đo, không bằng suy luận: bản đầu tiên
    của tệp này dùng `gen_random_uuid()` và làm đỏ 12 bài kiểm migration.*
    """
    bind = op.get_bind()
    wanting = bind.execute(
        sa.text(
            """
            SELECT w.id, w.owner_user_id
            FROM workspaces w
            WHERE w.workspace_agent_id IS NULL
              AND NOT EXISTS (
                  SELECT 1 FROM mariuses m
                  WHERE m.workspace_id = w.id AND m.role = 'Workspace Agent'
              )
              AND NOT EXISTS (
                  SELECT 1 FROM mariuses m
                  WHERE m.workspace_id = w.id AND lower(m.name) = lower(:name)
              )
            """
        ).bindparams(name=HOST_NAME)
    ).fetchall()

    for raw_workspace_id, owner_user_id in wanting:
        # Cùng một cột, hai kiểu Python. Postgres có kiểu `uuid` thật nên driver trả về một
        # `UUID`; SQLite lưu nó thành chuỗi 32 ký tự nên trả về `str`. Ép về một kiểu ngay ở đây
        # chứ không để chỗ buộc tham số nhận cả hai — *đo được, không suy ra: bản trước đưa
        # thẳng thứ đọc lên vào `sa.Uuid` và đổ trên SQLite với `'str' object has no attribute
        # 'hex'`, trong khi Postgres chạy trơn.*
        workspace_id = (
            raw_workspace_id if isinstance(raw_workspace_id, UUID) else UUID(str(raw_workspace_id))
        )
        host_id = uuid4()
        # Kiểu của tham số nói ra hẳn hoi, không để driver đoán. Postgres có kiểu `uuid` thật và
        # từ chối một chuỗi đưa vào cột ấy; SQLite thì nhận. *Đo được, không suy ra: bản trước
        # của tệp này truyền `str(uuid4())` — xanh trên SQLite trong bộ kiểm, và đổ ngay khi
        # chạy trên Postgres thật với `column "id" is of type uuid but expression is of type
        # character varying`.* `sa.Uuid` là kiểu chính các model dùng, nên nó ghi ra đúng hình
        # dạng mỗi dialect đang lưu.
        bind.execute(
            sa.text(
                """
                INSERT INTO mariuses (
                    id, workspace_id, name, role, skills, adapter_type, adapter_config,
                    skill_ids, owner_user_id, liveness, created_at, updated_at,
                    probe_attempts, backoff_step, instructions, description, runtime_options
                ) VALUES (
                    :id, :workspace_id, :name, 'Workspace Agent', '[]', '', '{}',
                    '[]', :owner_user_id, 'offline', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP,
                    0, 0, :instructions, '', '{}'
                )
                """
            ).bindparams(
                sa.bindparam("id", value=host_id, type_=sa.Uuid),
                sa.bindparam("workspace_id", value=workspace_id, type_=sa.Uuid),
                sa.bindparam("name", value=HOST_NAME, type_=sa.String),
                sa.bindparam("owner_user_id", value=owner_user_id, type_=sa.String),
                sa.bindparam("instructions", value=HOST_INSTRUCTIONS, type_=sa.Text),
            )
        )
        bind.execute(
            sa.text(
                "UPDATE workspaces SET workspace_agent_id = :host WHERE id = :ws"
            ).bindparams(
                sa.bindparam("host", value=host_id, type_=sa.Uuid),
                sa.bindparam("ws", value=workspace_id, type_=sa.Uuid),
            )
        )

    # Không gian làm việc trước #32 nhận người chủ nhà bằng **vai** chứ không bằng con trỏ. Nếu
    # có cái nào như thế thì nó đã bị loại khỏi câu SELECT trên (đúng vậy), nhưng con trỏ của nó
    # vẫn rỗng — và đó là thứ #32 nói phải là nguồn sự thật duy nhất.
    op.execute(
        """
        UPDATE workspaces
        SET workspace_agent_id = (
            SELECT m.id FROM mariuses m
            WHERE m.workspace_id = workspaces.id AND m.role = 'Workspace Agent'
            ORDER BY m.created_at, m.id
            LIMIT 1
        )
        WHERE workspace_agent_id IS NULL
          AND EXISTS (
              SELECT 1 FROM mariuses m
              WHERE m.workspace_id = workspaces.id AND m.role = 'Workspace Agent'
          )
        """
    )


def downgrade() -> None:
    # Không gỡ lại. Người chủ nhà là một agent thật: một người có thể đã đổi tên nó, đã sửa chỉ
    # dẫn, đã đặt nó vào một runtime, đã giao việc cho nó. Xoá theo tên và theo vai ở đây là xoá
    # cả những con ấy. Bỏ cột thì được, bỏ một đồng nghiệp thì không.
    pass
