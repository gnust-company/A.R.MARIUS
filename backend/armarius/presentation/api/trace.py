"""Run trace endpoints — durable list + live SSE stream (§8.1 observability).

A run belongs to a task, a task to a project, a project to one workspace. Every route
here resolves that chain against the caller and answers *not found* when it does not lead
back to them (Constitution I, FR-081) — a run trace carries prompts and agent output, so
reading someone else's is reading their work.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from uuid import UUID

from fastapi import APIRouter, Request
from sse_starlette.sse import EventSourceResponse

from armarius.domain.entities.run import RunStatus
from armarius.presentation.api.auth import CurrentUser
from armarius.presentation.api.scoping import own_run, own_task
from armarius.presentation.deps import ContainerDep
from armarius.presentation.schemas import RunEventOut, RunOut

router = APIRouter(prefix="/v1", tags=["trace"])

_TERMINAL = {RunStatus.COMPLETED, RunStatus.FAILED, RunStatus.TIMED_OUT, RunStatus.STOPPED}


@router.get("/tasks/{task_id}/runs", response_model=list[RunOut])
async def list_runs(
    task_id: UUID, container: ContainerDep, user: CurrentUser
) -> list[RunOut]:
    await own_task(container, user, task_id)
    items = await container.runs.list_by_task(task_id)
    return [RunOut.model_validate(r) for r in items]


@router.get("/runs/{run_id}", response_model=RunOut)
async def get_run(
    run_id: UUID, container: ContainerDep, user: CurrentUser
) -> RunOut:
    return RunOut.model_validate(await own_run(container, user, run_id))


@router.get("/runs/{run_id}/events", response_model=list[RunEventOut])
async def list_run_events(
    run_id: UUID, container: ContainerDep, user: CurrentUser
) -> list[RunEventOut]:
    await own_run(container, user, run_id)
    items = await container.runs.events(run_id)
    return [RunEventOut.model_validate(e) for e in items]


@router.get("/runs/{run_id}/stream")
async def stream_run_events(
    run_id: UUID, request: Request, container: ContainerDep, user: CurrentUser
) -> EventSourceResponse:
    """Replay the durable trace, then live-tail until the run finishes."""
    await own_run(container, user, run_id)

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
        # A different shape from the durable rows above — the live bus yields plain dicts,
        # so it gets its own name rather than rebinding `event` to a second type.
        async for live in container.event_bus.subscribe(run_id):
            if await request.is_disconnected():
                break
            yield frame(
                live.get("type", "message"), live.get("seq"), live.get("payload", {})
            )

    return EventSourceResponse(generator())
