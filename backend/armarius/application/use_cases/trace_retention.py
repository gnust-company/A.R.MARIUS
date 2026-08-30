"""Hạn giữ nhật ký đầy đủ — và vì sao nó là hạn của riêng nó (T101, FR-050).

Thư mục làm việc trên một cái máy được dọn theo nhịp của cái máy ấy và vì lý do của cái máy ấy:
đĩa. Nhật ký thì là bản ghi *agent đã làm gì và vì sao nó kết luận như vậy*, và người ta đọc nó
hàng tháng sau, để trả lời một câu hỏi về công việc đã có người ký nhận (SC-013). Buộc hai thứ ấy
vào chung một con số là làm sai một trong hai, nên chúng là hai thiết lập.

Đếm từ **đồng hồ của chính sự kiện**, không phải từ lúc hàng được ghi. Hai thứ ấy gần nhau nhưng
không phải một, và cái người ta hỏi bao giờ cũng là *chuyện ấy xảy ra lâu chưa*.
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import Callable
from datetime import datetime, timedelta

from armarius.application.use_cases.types import UowFactory
from armarius.shared.clock import utcnow
from armarius.shared.config import settings
from armarius.shared.logging import get_logger

logger = get_logger(__name__)


class TraceRetention:
    """Quét nhật ký quá hạn, theo nhịp của riêng nó."""

    def __init__(
        self,
        uow_factory: UowFactory,
        *,
        keep_days: int | None = None,
        every_seconds: float | None = None,
        clock: Callable[[], datetime] = utcnow,
    ) -> None:
        self._uow = uow_factory
        self._keep = timedelta(
            days=keep_days if keep_days is not None else settings.run_trace_retention_days
        )
        self._every = (
            every_seconds
            if every_seconds is not None
            else settings.run_trace_sweep_interval_seconds
        )
        self._clock = clock
        self._task: asyncio.Task | None = None

    @property
    def cutoff(self) -> datetime:
        """Mốc: cũ hơn mốc này là quá hạn."""
        return self._clock() - self._keep

    async def sweep(self) -> int:
        """Bỏ đi những gì đã quá hạn, trả về đã bỏ bao nhiêu sự kiện."""
        async with self._uow() as uow:
            gone = await uow.run_events.forget_before(self.cutoff)
            await uow.commit()
        if gone:
            logger.info("forgot %d run event(s) past their keeping", gone)
        return gone

    def start(self) -> None:
        """Chạy vòng quét nền (gọi nhiều lần cũng chỉ có một vòng)."""
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._loop())

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None

    async def _loop(self) -> None:
        while True:
            try:
                await self.sweep()
            except Exception:  # pragma: no cover - một nhịp hỏng không được giết cả vòng
                logger.exception("could not sweep the run log")
            await asyncio.sleep(self._every)
