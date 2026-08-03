"""Đọc thẳng cơ sở dữ liệu mà ứng dụng đang chạy trên đó, dùng cho bài kiểm mức giao tiếp.

Vài thứ có thật và quan trọng lại **không** có lối ra ở mặt giao tiếp — lệnh đánh thức là
một. Kiểm nó bằng cách mở thêm một lối vào chỉ để bài kiểm dùng là làm hỏng mặt giao tiếp
vì lý do của bài kiểm. Thay vào đó, bài kiểm soi thẳng dữ liệu, đúng như khi ta dựng dịch
vụ thật lên rồi mở cơ sở dữ liệu ra xem.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import select

from armarius.infrastructure.database.models import WakeupModel


def app_uow():
    """Một đơn vị công việc mở trên đúng cơ sở dữ liệu của ứng dụng đang phục vụ."""
    from armarius.main import app

    factory: Any = app.state.container.uow_factory
    return factory()


async def wakeups_for_task(task_id: str | UUID) -> list[dict]:
    """Mọi lệnh đánh thức đã đặt cho một đầu việc, cũ nhất trước."""
    async with app_uow() as uow:
        session = uow._session  # noqa: SLF001 — bài kiểm soi dữ liệu, không có lối công khai
        assert session is not None
        rows = (
            await session.execute(
                select(WakeupModel)
                .where(WakeupModel.task_id == UUID(str(task_id)))
                .order_by(WakeupModel.created_at, WakeupModel.id)
            )
        ).scalars()
        return [
            {
                "marius_id": str(r.marius_id),
                "source": r.source,
                "reason": r.reason,
                "status": r.status,
            }
            for r in rows
        ]
