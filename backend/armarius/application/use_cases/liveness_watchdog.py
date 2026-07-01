"""Liveness watchdog (LLD §10) — the background clock that drives the LivenessEngine.

The engine is pure per-tick logic; something has to *call* it. This watchdog is that
caller: a single background loop that, every ``interval_seconds``, advances every Marius in
every workspace one tick — firing probes as the FSM decides and letting silent agents decay
ONLINE → CHECKING → OFFLINE over time. It is started in the app lifespan and cancelled on
shutdown; the loop body (`tick_all`) is separately callable so tests can drive it
deterministically off a fixed clock.
"""

from __future__ import annotations

import asyncio
import contextlib
from datetime import datetime

from armarius.application.use_cases.liveness import LivenessEngine
from armarius.application.use_cases.types import UowFactory
from armarius.shared.clock import utcnow
from armarius.shared.logging import get_logger

logger = get_logger(__name__)


class LivenessWatchdog:
    def __init__(
        self,
        uow_factory: UowFactory,
        liveness: LivenessEngine,
        *,
        interval_seconds: float = 30.0,
        clock=utcnow,
    ) -> None:
        self._uow = uow_factory
        self._liveness = liveness
        self._interval = interval_seconds
        self._clock = clock
        self._task: asyncio.Task[None] | None = None

    async def tick_all(self, now: datetime | None = None) -> int:
        """Advance every Marius in every workspace one tick. Returns the workspace count."""
        now = now or self._clock()
        async with self._uow() as uow:
            workspaces = list(await uow.workspaces.list())
        for ws in workspaces:
            await self._liveness.tick(workspace_id=ws.id, now=now)
        return len(workspaces)

    # ── background lifecycle ─────────────────────────────────────────────────────
    def start(self) -> None:
        """Spawn the background loop (idempotent)."""
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        """Cancel the background loop and await its unwind."""
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None

    async def _run(self) -> None:
        while True:
            try:
                await self.tick_all()
            except Exception:  # pragma: no cover - a bad tick must not kill the loop
                logger.exception("liveness watchdog tick failed")
            await asyncio.sleep(self._interval)
