"""Echo adapter — a fake runtime for local demos and tests.

Emits a Hermes-shaped event sequence (run.started → assistant.delta → tool.* →
assistant.completed → run.completed) so the live trace, session store and wake loop
can be exercised end-to-end without a real gateway. Selected by adapter_type "echo".
"""

from __future__ import annotations

import asyncio

from armarius.application.ports.adapter import (
    AdapterCapabilities,
    Diagnostics,
    ExecContext,
    ExecResult,
    MariusAdapter,
)
from armarius.domain.entities.run import RunStatus


class EchoAdapter(MariusAdapter):
    type = "echo"
    capabilities = AdapterCapabilities(resumable=True, streaming=True, transport="process")

    def __init__(self, *, step_delay: float = 0.4) -> None:
        self._delay = step_delay

    async def execute(self, ctx: ExecContext) -> ExecResult:
        session_params = ctx.session_params or {"session_id": f"echo:{ctx.task_id}"}
        emit = ctx.on_event

        async def ev(event_type: str, payload: dict) -> None:
            if emit is not None:
                await emit(event_type, payload)
            await asyncio.sleep(self._delay)

        await ev("run.started", {"run_id": str(ctx.run_id)})
        await ev("message.started", {"role": "assistant"})
        for chunk in ("Reading the task brief", " and the thread", " to plan my work."):
            await ev("assistant.delta", {"text": chunk})
        await ev("tool.started", {"tool_name": "read_directory", "args": {}})
        await ev("tool.completed", {"tool_name": "read_directory", "ok": True})
        await ev(
            "assistant.delta",
            {"text": " I have what I need; recording progress on the task."},
        )
        await ev("assistant.completed", {"finish_reason": "stop"})
        await ev(
            "run.completed",
            {"usage": {"input_tokens": 320, "output_tokens": 96, "total_tokens": 416}},
        )

        return ExecResult(
            status=RunStatus.COMPLETED,
            session_params=session_params,
            session_display_id=session_params.get("session_id"),
            external_run_id=str(ctx.run_id),
            usage={"input_tokens": 320, "output_tokens": 96, "total_tokens": 416},
        )

    async def test_environment(self, config: dict) -> Diagnostics:
        return Diagnostics(ok=True, detail="echo adapter is always available")
