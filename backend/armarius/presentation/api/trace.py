"""Run trace endpoints — durable list + live SSE stream (§8.1 observability).

A run belongs to a task, a task to a project, a project to one workspace. Every route
here resolves that chain against the caller and answers *not found* when it does not lead
back to them (Constitution I, FR-081) — a run trace carries prompts and agent output, so
reading someone else's is reading their work.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query, Request
from sse_starlette.sse import EventSourceResponse

from armarius.domain.entities.run import RunEvent, RunStatus
from armarius.presentation.api.auth import CurrentUser
from armarius.presentation.api.scoping import own_run, own_task
from armarius.presentation.deps import ContainerDep
from armarius.presentation.schemas import RunEventFullOut, RunEventOut, RunOut
from armarius.shared.errors import NotFound

router = APIRouter(prefix="/v1", tags=["trace"])

_TERMINAL = {RunStatus.COMPLETED, RunStatus.FAILED, RunStatus.TIMED_OUT, RunStatus.STOPPED}


def about_the_record(event: RunEvent) -> dict:
    """What a stored row keeps beside its payload, carried beside it on the stream too.

    The backlog a stream replays and the live tail after it are the same run, and a reader
    cannot be shown two versions of it depending on which half a given event arrived in.
    Sending only the payload here is what made a replayed event lose *why it is short* and
    *whether anything was taken out of it* — the very facts FR-047 exists to keep, and the ones
    the list endpoint has carried since T096.

    Every key here is a field of :class:`RunEventOut` that is not the event itself, and a test
    holds it to that: a column added to the stored row and forgotten here would put the two
    roads out of step again, silently, in the direction that shows less.
    """
    return {
        "truncated": event.truncated,
        "original_byte_size": event.original_byte_size,
        "omission_reason": event.omission_reason,
        "redacted": event.redacted,
        "full_field": event.full_field,
        "full_byte_size": event.full_byte_size,
        "created_at": event.created_at.isoformat() if event.created_at else None,
    }


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


# How many events one ask may bring back. A run of a thousand still opens in one page
# (SC-014); a run of a hundred thousand is walked with `after_seq` rather than refused.
MAX_EVENTS_PER_PAGE = 1000


@router.get("/runs/{run_id}/events", response_model=list[RunEventOut])
async def list_run_events(
    run_id: UUID,
    container: ContainerDep,
    user: CurrentUser,
    type: Annotated[list[str] | None, Query()] = None,
    after_seq: Annotated[int | None, Query(ge=0)] = None,
    limit: Annotated[int, Query(ge=1, le=MAX_EVENTS_PER_PAGE)] = MAX_EVENTS_PER_PAGE,
) -> list[RunEventOut]:
    """The run's durable log, in order, filtered and walked (FR-016, FR-052, SC-013).

    `type` may be given more than once and reads as *any of these*. It is the difference
    between a log and a usable log: finding one tool call among a thousand lines by eye is
    not finding it.

    `after_seq` walks rather than pages by offset. The numbering is the run's own and does not
    shift, so a screen that has read up to a number can ask for what is past it and get exactly
    that, however many events landed meanwhile.
    """
    await own_run(container, user, run_id)
    items = await container.runs.events(
        run_id, types=type or None, after_seq=after_seq, limit=limit
    )
    return [RunEventOut.model_validate(e) for e in items]


@router.get("/runs/{run_id}/events/{seq}/full", response_model=RunEventFullOut)
async def read_run_event_in_full(
    run_id: UUID, seq: int, container: ContainerDep, user: CurrentUser
) -> RunEventFullOut:
    """The whole of a long field the list only carried the opening of (FR-049).

    Its own call because that is the whole point of the split: the list stays small enough to
    open a run of a thousand events, and the megabyte is fetched for the one event somebody
    actually opened.

    An event with nothing kept apart answers *not found*, the same as an event that is not
    there — asking for the rest of something that has no rest is asking for a thing that does
    not exist, and there is no third answer worth inventing.
    """
    await own_run(container, user, run_id)
    found = await container.runs.full_text(run_id, seq)
    if found is None:
        raise NotFound("run_event_full_text_not_found")
    field, content, byte_size = found
    return RunEventFullOut(seq=seq, field=field, byte_size=byte_size, content=content)


@router.get("/runs/{run_id}/stream")
async def stream_run_events(
    run_id: UUID, request: Request, container: ContainerDep, user: CurrentUser
) -> EventSourceResponse:
    """Replay the durable trace, then live-tail until the run finishes."""
    await own_run(container, user, run_id)

    def frame(event_type: str, seq: int | None, payload: dict, about: dict | None = None) -> dict:
        # Emit as default "message" events so the browser EventSource.onmessage
        # receives every event type (event names are carried inside the JSON).
        return {
            "data": json.dumps(
                {"type": event_type, "seq": seq, "payload": payload, **(about or {})}
            )
        }

    async def generator() -> AsyncIterator[dict]:
        for event in await container.runs.events(run_id):
            yield frame(event.type, event.seq, event.payload, about_the_record(event))
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
