"""Hybrid SSE — the server→browser streams (API_CONTRACT §2, §8; spec 001).

  - ``GET /v1/workspaces/{ws}/events``   — always-on workspace control-plane stream.
  - ``GET /v1/tasks/{task_id}/stream``   — per-task live run trace, opened on demand.
  - ``GET /v1/projects/{id}/events``     — project board: phase, task status, stall flags.
  - ``GET /v1/inbox/events``             — the caller's own inbox: new items, resolutions.

Both are **Web-App-only** (JWT-scoped; agents never read SSE), frame one event per
``event:``/``data:``/``id:`` block, and honour ``Last-Event-ID`` (header or
``?last_event_id=``) for resume by replaying everything the client missed.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from uuid import UUID

from fastapi import APIRouter, Request
from sse_starlette.sse import EventSourceResponse

from armarius.infrastructure.events.topic_bus import patron_topic, project_topic
from armarius.presentation.api.auth import CurrentUser
from armarius.presentation.deps import ContainerDep
from armarius.shared.errors import NotFound

router = APIRouter(prefix="/v1", tags=["events"])


def _resume_from(request: Request) -> int:
    """Last-Event-ID — browsers resend it as a header; we also accept a query param."""
    raw = request.headers.get("last-event-id") or request.query_params.get("last_event_id")
    try:
        return int(raw) if raw is not None else 0
    except ValueError:
        return 0


def _is_live(request: Request) -> bool:
    """Default: an always-on live stream. ``?live=0`` is a finite **catch-up** response —
    it replays everything after ``Last-Event-ID`` and closes (a long-poll fallback for
    clients/proxies that cannot hold a persistent SSE connection)."""
    return request.query_params.get("live", "1").lower() not in ("0", "false", "no")


def _frame(event) -> dict:
    return {"id": str(event.seq), "event": event.type, "data": json.dumps(event.data)}


async def _require_own_workspace(
    container, user, workspace_id: UUID | None, not_found: str
) -> None:
    """Every stream is workspace-scoped: not yours reads as *not found*, never *forbidden*,
    so a caller cannot probe for the existence of another workspace's rows (Constitution I)."""
    ws = (
        await container.workspaces.get_workspace(workspace_id)
        if workspace_id is not None
        else None
    )
    if ws is None or ws.owner_user_id != str(user.id):
        raise NotFound(not_found)


async def _stream(container, request: Request, topic: str) -> EventSourceResponse:
    after = _resume_from(request)
    live = _is_live(request)
    bus = container.control_bus

    async def generator() -> AsyncIterator[dict]:
        # Attach the live queue BEFORE snapshotting the backlog so nothing slips through
        # the hand-off; de-duplicate the overlap by seq.
        queue, unregister = bus.register(topic)
        try:
            last = after
            for event in bus.backlog(topic, after_seq=last):
                last = event.seq
                yield _frame(event)
            if not live:
                # Catch-up mode: the backlog is a snapshot, so an event published while we
                # were yielding it landed on the live queue but not the snapshot. Drain the
                # queue (de-duplicated by seq) so this finite response is gap-free, then close.
                while True:
                    try:
                        event = queue.get_nowait()
                    except asyncio.QueueEmpty:
                        break
                    if event.seq <= last:
                        continue
                    last = event.seq
                    yield _frame(event)
                return
            while True:
                # Poll with a short timeout so a disconnected client is noticed even while
                # the topic is idle. Cancelling a queue.get() (unlike a generator) is safe.
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=1.0)
                except TimeoutError:
                    if await request.is_disconnected():
                        break
                    continue
                if event.seq <= last:
                    continue
                last = event.seq
                yield _frame(event)
        finally:
            unregister()

    return EventSourceResponse(generator())


@router.get("/workspaces/{workspace_id}/events")
async def workspace_events(
    workspace_id: UUID,
    request: Request,
    container: ContainerDep,
    user: CurrentUser,
) -> EventSourceResponse:
    await _require_own_workspace(container, user, workspace_id, "workspace_not_found")
    return await _stream(container, request, f"ws:{workspace_id}")


@router.get("/tasks/{task_id}/stream")
async def task_stream(
    task_id: UUID,
    request: Request,
    container: ContainerDep,
    user: CurrentUser,
) -> EventSourceResponse:
    task = await container.tasks.get(task_id)
    if task is None:
        raise NotFound("task_not_found")
    project = await container.projects.get_project(task.project_id)
    if project is None:
        raise NotFound("task_not_found")
    await _require_own_workspace(container, user, project.workspace_id, "task_not_found")
    return await _stream(container, request, f"task:{task_id}")


@router.get("/projects/{project_id}/leader-chat/stream")
async def leader_chat_stream(
    project_id: UUID,
    request: Request,
    container: ContainerDep,
    user: CurrentUser,
) -> EventSourceResponse:
    """Live trace of the project's Chat-with-Leader turn (#82) — the Leader's reply
    streams here as ``assistant.delta`` events, plus ``chat.state``/``leader.message``."""
    project = await container.projects.get_project(project_id)
    if project is None:
        raise NotFound("project_not_found")
    await _require_own_workspace(container, user, project.workspace_id, "project_not_found")
    return await _stream(container, request, f"leader-chat:{project_id}")


@router.get("/projects/{project_id}/events")
async def project_events(
    project_id: UUID,
    request: Request,
    container: ContainerDep,
    user: CurrentUser,
) -> EventSourceResponse:
    """Project board channel (spec 001) — phase changes, task status, stall flags."""
    project = await container.projects.get_project(project_id)
    if project is None:
        raise NotFound("project_not_found")
    await _require_own_workspace(container, user, project.workspace_id, "project_not_found")
    return await _stream(container, request, project_topic(project_id))


@router.get("/inbox/events")
async def inbox_events(
    request: Request,
    container: ContainerDep,
    user: CurrentUser,
) -> EventSourceResponse:
    """The caller's inbox channel (spec 001). Keyed by the authenticated user, so there
    is no id to tamper with and no way to subscribe to someone else's inbox."""
    return await _stream(container, request, patron_topic(user.id))
