"""Run trace endpoints — durable list + live SSE stream (§8.1 observability)."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from uuid import UUID

from fastapi import APIRouter, Request
from sse_starlette.sse import EventSourceResponse

from armarius.domain.entities.run import RunStatus
from armarius.presentation.deps import ContainerDep
from armarius.presentation.schemas import RunEventOut, RunOut

router = APIRouter(prefix="/v1", tags=["trace"])

_TERMINAL = {RunStatus.COMPLETED, RunStatus.FAILED, RunStatus.TIMED_OUT, RunStatus.STOPPED}


@router.get("/tasks/{task_id}/runs", response_model=list[RunOut])
async def list_runs(task_id: UUID, container: ContainerDep) -> list[RunOut]:
    items = await container.runs.list_by_task(task_id)
    return [RunOut.model_validate(r) for r in items]


@router.get("/runs/{run_id}", response_model=RunOut)
async def get_run(run_id: UUID, container: ContainerDep) -> RunOut:
    run = await container.runs.get(run_id)
    if run is None:
        raise LookupError("run not found")
    return RunOut.model_validate(run)


@router.get("/runs/{run_id}/events", response_model=list[RunEventOut])
async def list_run_events(run_id: UUID, container: ContainerDep) -> list[RunEventOut]:
    items = await container.runs.events(run_id)
    return [RunEventOut.model_validate(e) for e in items]


@router.get("/runs/{run_id}/stream")
async def stream_run_events(
    run_id: UUID, request: Request, container: ContainerDep
) -> EventSourceResponse:
    """Replay the durable trace, then live-tail until the run finishes."""
    run = await container.runs.get(run_id)
    if run is None:
        raise LookupError("run not found")

    def frame(event_type: str, seq: int | None, payload: dict) -> dict:
        # Emit as default "message" events so the browser EventSource.onmessage
        # receives every event type (event names are carried inside the JSON).
        return {"data": json.dumps({"type": event_type, "seq": seq, "payload": payload})}

    async def generator() -> AsyncIterator[dict]:
        for event in await container.runs.events(run_id):
            yield frame(event.type, event.seq, event.payload)
        fresh = await container.runs.get(run_id)
        if fresh is not None and fresh.status in _TERMINAL:
            yield frame("run.finished", None, {"status": str(fresh.status)})
            return
        async for event in container.event_bus.subscribe(run_id):
            if await request.is_disconnected():
                break
            yield frame(
                event.get("type", "message"), event.get("seq"), event.get("payload", {})
            )

    return EventSourceResponse(generator())
