"""Wake engine — the heart of Armarius (§4.3, §8.1).

Responsibilities:
  * enqueue task-scoped wakes (event or self/liveness), with in-process coalescing;
  * for each wake, open/resume the (marius, adapter, task) session and run one bounded
    adapter turn;
  * tee the adapter's streamed events to a durable run-log AND a live event bus;
  * finalise the run, persist the new session handle, and consult the self-wake policy
    to decide on a bounded continuation/nudge.

There is intentionally no global timer: wakes are either driven by world events or by
this policy reacting to a finished/dropped run.
"""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from uuid import UUID

from armarius.application.ports.adapter import AdapterRegistry, ExecContext, ExecResult
from armarius.application.ports.event_bus import EventBus
from armarius.application.ports.task_trace import TaskTracePublisher
from armarius.application.use_cases.onboarding import credential_file_for
from armarius.application.use_cases.types import UowFactory
from armarius.domain.entities.comment import Comment
from armarius.domain.entities.marius import Liveness, Marius
from armarius.domain.entities.run import Run, RunEvent, RunStatus, WakeSource
from armarius.domain.entities.session import AgentTaskSession
from armarius.domain.entities.task import Task, TaskStatus
from armarius.domain.entities.wakeup import WakeupRequest, WakeupStatus
from armarius.domain.entities.workspace import Project, Workspace
from armarius.domain.services.wake_policy import decide_self_wake
from armarius.domain.services.wake_prompt import (
    DirectoryEntry,
    ThreadMessage,
    WakeContext,
    build_wake_prompt,
)
from armarius.shared.clock import utcnow
from armarius.shared.logging import get_logger

logger = get_logger(__name__)

# Event types we persist to the durable trace. Per-token deltas stream live only.
_DURABLE_EVENT = lambda t: t != "assistant.delta"  # noqa: E731

_BLOCK_REASON_STATUSES = {TaskStatus.BLOCKED, TaskStatus.BACKLOG}


class WakeEngine:
    def __init__(
        self,
        uow_factory: UowFactory,
        registry: AdapterRegistry,
        event_bus: EventBus,
        *,
        run_timeout_seconds: int = 900,
        max_continuation_attempts: int = 3,
        task_trace: TaskTracePublisher | None = None,
    ) -> None:
        self._uow = uow_factory
        self._registry = registry
        self._bus = event_bus
        # Optional per-task tee: mirrors run events onto the `task:{id}` SSE channel (§8.1).
        self._task_trace = task_trace
        self._timeout = run_timeout_seconds
        self._max_attempts = max_continuation_attempts
        # In-process coalescing: (marius_id, task_id) -> active run_id.
        self._active: dict[tuple[UUID, UUID], UUID] = {}
        self._lock = asyncio.Lock()
        self._bg: set[asyncio.Task[None]] = set()

    # ------------------------------------------------------------------ enqueue

    async def enqueue(
        self,
        *,
        marius_id: UUID,
        task_id: UUID,
        source: WakeSource,
        reason: str | None = None,
        continuation_attempt: int = 0,
    ) -> UUID:
        """Queue a task-scoped wake. Returns the run id (existing one if coalesced)."""
        async with self._lock:
            key = (marius_id, task_id)
            if key in self._active:
                run_id = self._active[key]
                async with self._uow() as uow:
                    await uow.wakeups.add(
                        WakeupRequest(
                            marius_id=marius_id,
                            task_id=task_id,
                            source=source,
                            reason=reason,
                            status=WakeupStatus.COALESCED,
                            run_id=run_id,
                            created_at=utcnow(),
                        )
                    )
                    await uow.commit()
                logger.info("wake coalesced into run %s (%s)", run_id, source)
                return run_id

            async with self._uow() as uow:
                task = await uow.tasks.get(task_id)
                marius = await uow.mariuses.get(marius_id)
                if task is None or marius is None:
                    raise LookupError("task or marius not found")
                run = Run(
                    project_id=task.project_id,
                    marius_id=marius_id,
                    task_id=task_id,
                    adapter_type=marius.adapter_type,
                    wake_source=source,
                    trigger_detail=reason,
                    status=RunStatus.QUEUED,
                    continuation_attempt=continuation_attempt,
                    created_at=utcnow(),
                )
                run = await uow.runs.add(run)
                await uow.wakeups.add(
                    WakeupRequest(
                        marius_id=marius_id,
                        task_id=task_id,
                        source=source,
                        reason=reason,
                        status=WakeupStatus.DISPATCHED,
                        run_id=run.id,
                        created_at=utcnow(),
                    )
                )
                await uow.commit()

            self._active[key] = run.id

        bg = asyncio.create_task(self._execute_run(run.id, marius_id, task_id))
        self._bg.add(bg)
        bg.add_done_callback(self._bg.discard)
        return run.id

    # -------------------------------------------------------------- run executor

    async def _execute_run(self, run_id: UUID, marius_id: UUID, task_id: UUID) -> None:
        try:
            await self._do_execute_run(run_id)
        except Exception:  # pragma: no cover - defensive
            logger.exception("run %s crashed", run_id)
        finally:
            async with self._lock:
                self._active.pop((marius_id, task_id), None)

    async def _do_execute_run(self, run_id: UUID) -> None:
        async with self._uow() as uow:
            run = await uow.runs.get(run_id)
            if run is None:
                return
            task = await uow.tasks.get(run.task_id) if run.task_id else None
            marius = await uow.mariuses.get(run.marius_id) if run.marius_id else None
            if task is None or marius is None:
                return

            session = await uow.sessions.get_for(marius.id, marius.adapter_type, task.id)
            directory = list(await uow.mariuses.list_by_workspace(marius.workspace_id))
            new_messages = await self._new_messages(uow, task, marius)
            workspace = await uow.workspaces.get(marius.workspace_id)
            project = await uow.projects.get(task.project_id)

            prompt = build_wake_prompt(
                _wake_context(run, marius, task, directory, new_messages, workspace, project)
            )

            run.status = RunStatus.RUNNING
            run.started_at = utcnow()
            run.session_id_before = (
                str(session.session_params_json) if session else None
            )
            await uow.runs.update(run)
            marius.liveness = Liveness.WORKING
            marius.last_seen_at = utcnow()
            marius.turn_started_at = utcnow()  # arm the hung_after watchdog (silence-since-turn)
            await uow.mariuses.update(marius)
            await uow.commit()

            await self._bus.publish(
                run_id, {"type": "run.queued", "payload": {"prompt_preview": prompt[:400]}}
            )
            await self._tee_task(task.id, "run.queued", {"prompt_preview": prompt[:400]})

            seq = 0

            async def on_event(event_type: str, payload: dict) -> None:
                nonlocal seq
                seq += 1
                if _DURABLE_EVENT(event_type):
                    await uow.run_events.add(
                        RunEvent(
                            run_id=run_id,
                            seq=seq,
                            type=event_type,
                            payload=payload,
                            created_at=utcnow(),
                        )
                    )
                    run.last_output_at = utcnow()
                    await uow.runs.update(run)
                    await uow.commit()
                await self._bus.publish(
                    run_id, {"seq": seq, "type": event_type, "payload": payload}
                )
                # Tee only durable lifecycle events to the Room's per-task channel; token
                # deltas stream on the per-run trace only (else 1000 deltas flood the Room).
                if _DURABLE_EVENT(event_type):
                    await self._tee_task(task.id, event_type, payload)

            adapter = self._registry.get(marius.adapter_type)
            ctx = ExecContext(
                prompt=prompt,
                adapter_config=marius.adapter_config,
                session_params=session.session_params_json if session else {},
                marius_id=marius.id,
                task_id=task.id,
                run_id=run_id,
                timeout_seconds=self._timeout,
                on_event=on_event,
            )

            try:
                result = await adapter.execute(ctx)
            except Exception as exc:  # adapter/runtime failure
                logger.exception("adapter execute failed for run %s", run_id)
                result = ExecResult(status=RunStatus.FAILED, error=str(exc))

            await self._finalise(uow, run, task, marius, session, result)

        # Self-wake policy runs after the transaction closes (may enqueue a new run).
        await self._maybe_self_wake(run_id)

    async def _finalise(
        self,
        uow,  # noqa: ANN001 - concrete UoW
        run: Run,
        task: Task,
        marius: Marius,
        session: AgentTaskSession | None,
        result: ExecResult,
    ) -> None:
        run.status = result.status
        run.finished_at = utcnow()
        run.usage_json = result.usage
        run.error = result.error
        run.external_run_id = result.external_run_id
        run.next_action = result.next_action
        run.session_id_after = result.session_display_id or (
            str(result.session_params) if result.session_params else None
        )
        await uow.runs.update(run)

        if result.session_params:
            if session is None:
                session = AgentTaskSession(
                    project_id=task.project_id,
                    marius_id=marius.id,
                    adapter_type=marius.adapter_type,
                    task_id=task.id,
                    created_at=utcnow(),
                )
            session.session_params_json = result.session_params
            session.session_display_id = result.session_display_id
            session.last_run_id = run.id
            session.last_error = result.error
            session.updated_at = utcnow()
            await uow.sessions.upsert(session)

        # Reload task: the agent may have changed status/next_action via the agent API.
        fresh_task = await uow.tasks.get(task.id)
        if fresh_task is not None and result.next_action and not fresh_task.next_action:
            fresh_task.next_action = result.next_action
            fresh_task.updated_at = utcnow()
            await uow.tasks.update(fresh_task)

        # Liveness reflects *reachability*, not the run's outcome. Any finalized run —
        # COMPLETED or not — means the agent runtime reached back, so it is available again
        # (IDLE) and the in-flight turn is cleared. HUNG is reserved for the watchdog (a turn
        # that went silent), never a non-COMPLETED status — otherwise a task that simply failed
        # or timed out would strand the agent "offline" forever (#82 liveness fix).
        marius.liveness = Liveness.IDLE
        marius.last_seen_at = utcnow()
        marius.turn_started_at = None
        await uow.mariuses.update(marius)
        await uow.commit()

        await self._bus.publish(
            run.id,
            {"type": "run.finished", "payload": {"status": str(result.status)}},
        )
        await self._tee_task(task.id, "run.finished", {"status": str(result.status)})

    async def _tee_task(self, task_id: UUID, event_type: str, payload: dict) -> None:
        """Mirror a run event onto the per-task SSE channel (no-op if not wired)."""
        if self._task_trace is not None:
            await self._task_trace.publish(task_id, event_type, payload)

    async def _maybe_self_wake(self, run_id: UUID) -> None:
        async with self._uow() as uow:
            run = await uow.runs.get(run_id)
            if run is None or run.task_id is None or run.marius_id is None:
                return
            task = await uow.tasks.get(run.task_id)
            if task is None:
                return
            artifact_count = await uow.artifacts.count_by_task(task.id)
            has_block_reason = (
                task.status in _BLOCK_REASON_STATUSES and bool(task.status_reason)
            )
            decision = decide_self_wake(
                task_status=task.status,
                run_status=run.status,
                has_next_action=bool(task.next_action),
                has_block_reason=has_block_reason,
                continuation_attempt=run.continuation_attempt,
                max_attempts=self._max_attempts,
            )
            marius_id = run.marius_id
            task_id = run.task_id
            next_attempt = run.continuation_attempt + 1
            _ = artifact_count  # reserved for future policy refinement

        if decision.escalate_to_human:
            logger.info("run %s escalated to human: %s", run_id, decision.reason)
            await self._bus.publish(
                run_id,
                {"type": "wake.escalated", "payload": {"reason": decision.reason}},
            )
            return
        if decision.should_wake and decision.source is not None:
            logger.info("self-wake (%s): %s", decision.source, decision.reason)
            await self.enqueue(
                marius_id=marius_id,
                task_id=task_id,
                source=decision.source,
                reason=decision.reason,
                continuation_attempt=next_attempt,
            )

    # ----------------------------------------------------------------- helpers

    async def _new_messages(self, uow, task: Task, marius: Marius) -> list[Comment]:  # noqa: ANN001
        runs = await uow.runs.list_by_task(task.id)
        last_finished = None
        for r in runs:
            if r.marius_id == marius.id and r.finished_at is not None:
                if last_finished is None or r.finished_at > last_finished:
                    last_finished = r.finished_at
        comments = list(await uow.comments.list_by_task(task.id))
        if last_finished is not None:
            comments = [
                c for c in comments if c.created_at and c.created_at > last_finished
            ]
        return comments[-30:]


def _wake_context(
    run: Run,
    marius: Marius,
    task: Task,
    directory: Sequence[Marius],
    messages: Sequence[Comment],
    workspace: Workspace | None = None,
    project: Project | None = None,
) -> WakeContext:
    dir_entries = [
        DirectoryEntry(
            name=m.name, role=m.role, skills=list(m.skills), liveness=str(m.liveness)
        )
        for m in directory
        if m.id != marius.id
    ]
    thread = [
        ThreadMessage(
            author=(
                "agent" if c.author_marius_id else ("human" if c.author_user_id else "system")
            ),
            body=c.body,
        )
        for c in messages
    ]
    return WakeContext(
        marius_name=marius.name,
        task_title=task.title,
        task_status=str(task.status),
        task_description=task.description,
        next_action=task.next_action,
        directory=dir_entries,
        new_messages=thread,
        source=run.wake_source,
        reason=run.trigger_detail,
        workspace_name=workspace.name if workspace else "",
        project_name=project.name if project else "",
        credential_file=(
            credential_file_for(marius, workspace.name) if workspace else None
        ),
    )
