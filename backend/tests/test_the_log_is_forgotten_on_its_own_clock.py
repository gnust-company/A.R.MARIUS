"""Nhật ký đầy đủ có hạn giữ của riêng nó (T101, FR-050).

Thư mục làm việc trên một cái máy được dọn theo nhịp của cái máy ấy và vì lý do của cái máy ấy:
đĩa. Nhật ký thì là bản ghi *agent đã làm gì và vì sao nó kết luận như vậy*, và người ta đọc nó
hàng tháng sau, để trả lời một câu hỏi về công việc đã có người ký nhận (SC-013). Buộc hai thứ ấy
vào chung một con số là làm sai một trong hai.

Đếm từ **đồng hồ của chính sự kiện**, không phải từ lúc hàng được ghi xuống. Hai thứ ấy gần nhau
nhưng không phải một, và cái người ta hỏi bao giờ cũng là *chuyện ấy xảy ra lâu chưa*.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select

from armarius.application.use_cases.trace_retention import TraceRetention
from armarius.infrastructure.daemon.models import RunEventBlobModel
from armarius.infrastructure.database.models import (
    RunEventModel,
    RunModel,
    WorkspaceModel,
)
from armarius.shared.config import settings

pytestmark = pytest.mark.anyio

NOW = datetime(2026, 8, 30, 12, 0, tzinfo=timezone.utc)


async def _a_run_with_events(uow_factory, ages: dict[int, timedelta | None]) -> UUID:
    """Một lượt chạy có sẵn vài sự kiện, mỗi cái già bằng chừng ấy. None = không có đồng hồ."""
    run_id, workspace_id = uuid4(), uuid4()
    async with uow_factory() as uow:
        session = uow._session  # noqa: SLF001 — bài kiểm soi thẳng dữ liệu
        session.add(WorkspaceModel(id=workspace_id, name="w", slug="w", created_at=NOW))
        session.add(
            RunModel(
                id=run_id,
                marius_id=uuid4(),
                adapter_type="daemon",
                status="completed",
                created_at=NOW,
            )
        )
        await session.flush()
        for seq, age in ages.items():
            event_id = uuid4()
            session.add(
                RunEventModel(
                    id=event_id,
                    run_id=run_id,
                    seq=seq,
                    type="assistant.message",
                    payload={"text": "x"},
                    created_at=None if age is None else NOW - age,
                )
            )
            await session.flush()
            session.add(
                RunEventBlobModel(
                    id=uuid4(),
                    run_event_id=event_id,
                    workspace_id=workspace_id,
                    field="text",
                    content="x" * 100,
                    byte_size=100,
                )
            )
        await uow.commit()
    return run_id


async def _left(uow_factory, run_id: UUID) -> tuple[list[int], int]:
    async with uow_factory() as uow:
        session = uow._session  # noqa: SLF001
        seqs = list(
            (
                await session.execute(
                    select(RunEventModel.seq)
                    .where(RunEventModel.run_id == run_id)
                    .order_by(RunEventModel.seq)
                )
            ).scalars()
        )
        blobs = await session.scalar(
            select(func.count())
            .select_from(RunEventBlobModel)
            .join(RunEventModel, RunEventModel.id == RunEventBlobModel.run_event_id)
            .where(RunEventModel.run_id == run_id)
        )
        return seqs, int(blobs or 0)


async def test_a_log_past_its_keeping_is_forgotten_and_a_fresh_one_is_not(uow_factory):
    run_id = await _a_run_with_events(
        uow_factory, {1: timedelta(days=40), 2: timedelta(days=31), 3: timedelta(days=2)}
    )

    gone = await TraceRetention(uow_factory, keep_days=30, clock=lambda: NOW).sweep()

    seqs, _ = await _left(uow_factory, run_id)
    assert gone == 2
    assert seqs == [3], "chỉ những gì còn trong hạn mới được ở lại"


async def test_what_was_kept_apart_goes_with_the_event_it_belonged_to(uow_factory):
    """Bỏ sự kiện mà để lại toàn văn của nó là giữ đúng cái phần lớn nhất và riêng tư nhất."""
    run_id = await _a_run_with_events(
        uow_factory, {1: timedelta(days=40), 2: timedelta(days=1)}
    )

    await TraceRetention(uow_factory, keep_days=30, clock=lambda: NOW).sweep()

    seqs, blobs = await _left(uow_factory, run_id)
    assert seqs == [2]
    assert blobs == 1, "toàn văn phải đi theo sự kiện đã bị bỏ"


async def test_an_event_with_no_clock_at_all_is_never_swept(uow_factory):
    """Không có câu trả lời cho *nó bao nhiêu tuổi*, và đoán một câu là lặng lẽ xoá đúng những
    hàng hệ thống này biết ít nhất."""
    run_id = await _a_run_with_events(uow_factory, {1: None, 2: timedelta(days=40)})

    await TraceRetention(uow_factory, keep_days=30, clock=lambda: NOW).sweep()

    seqs, _ = await _left(uow_factory, run_id)
    assert seqs == [1]


async def test_the_keeping_is_something_that_can_be_set_and_is_its_own_number(uow_factory):
    """FR-050 đòi hạn giữ đặt được và **tách khỏi** hạn giữ của thư mục làm việc."""
    assert settings.run_trace_retention_days == 30
    kept_longer = TraceRetention(uow_factory, keep_days=90, clock=lambda: NOW)
    assert kept_longer.cutoff == NOW - timedelta(days=90)
