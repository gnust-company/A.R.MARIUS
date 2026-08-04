"""Wake engine — the heart of Armarius (§4.3, §8.1).

Responsibilities:
  * enqueue task-scoped wakes (event or self/liveness), coalescing them in the database
    so one (agent, task) pair never has two wakes owed or two runs live (FR-050);
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
from armarius.domain.entities.project_context import ProjectContext
from armarius.domain.entities.role import Role
from armarius.domain.entities.run import (
    ACTIVE_RUN_STATUSES,
    Run,
    RunEvent,
    RunStatus,
    WakeSource,
)
from armarius.domain.entities.seat_grant import SeatGrantStatus
from armarius.domain.entities.session import AgentTaskSession
from armarius.domain.entities.task import Task, TaskStatus
from armarius.domain.entities.wakeup import (
    WakePairBusyError,
    WakeupRequest,
    WakeupStatus,
)
from armarius.domain.entities.workspace import Project, Workspace
from armarius.domain.services.wake_coalesce import merge_causes, stronger_source
from armarius.domain.services.wake_policy import decide_self_wake
from armarius.domain.services.wake_prompt import (
    DirectoryEntry,
    ProjectBrief,
    ThreadMessage,
    WakeContext,
    build_wake_prompt,
)
from armarius.shared.clock import utcnow
from armarius.shared.logging import get_logger

logger = get_logger(__name__)

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
        # Coalescing is decided in the database (FR-050). This lock only keeps the
        # common in-process case from doing redundant work — it is not the guarantee.
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
        """Queue a task-scoped wake. Returns the run id (the existing one if coalesced).

        FR-050 in one place: at most one pending wake and one live run per *(agent, task)*.
        The decision is made from the database, not from a dictionary in this process —
        which is what makes it survive a restart and hold across more than one worker.

        The lock below still helps (it keeps the common case from doing wasted work) but it
        is no longer what guarantees the invariant. The partial unique index is. If two
        callers race past the lock, the loser is told the pair is busy and folds in.
        """
        async with self._lock:
            for attempt in (0, 1):
                folded = await self._fold_into_pending(marius_id, task_id, source, reason)
                if folded is not None:
                    logger.info("wake coalesced into run %s (%s)", folded, source)
                    return folded
                try:
                    run_id = await self._open_run(
                        marius_id, task_id, source, reason, continuation_attempt
                    )
                except WakePairBusyError:
                    if attempt == 0:
                        continue  # someone opened a run between our read and our write
                    raise
                break
            else:  # pragma: no cover - the loop always returns or breaks
                raise RuntimeError("wake enqueue did not settle")

        self._spawn(run_id, marius_id, task_id)
        return run_id

    async def _fold_into_pending(
        self,
        marius_id: UUID,
        task_id: UUID,
        source: WakeSource,
        reason: str | None,
    ) -> UUID | None:
        """Merge one more cause into the wake this pair already owes, if there is one.

        Returns the run id the cause was folded into, or ``None`` when the pair is free.

        The question asked here is **"is a run still holding this pair?"**, not "is there a
        pending wake row?". Those come apart: a process stopped mid-turn closes its wake on
        the way out but cannot finalise the run it was driving. Keying off the wake row
        would then read the pair as free, try to open a second run, and be refused by the
        index — turning an ordinary restart into an error on the next comment.
        """
        async with self._uow() as uow:
            run = await uow.runs.get_active_for(marius_id, task_id)
            pending = list(await uow.wakeups.list_active_for(marius_id, task_id))
            if run is None:
                # No run holds the pair. Any wake row still marked pending is a leftover
                # that nothing will ever come back to close — retire it so the pair is
                # genuinely free rather than wedged behind a dead row.
                for stale in pending:
                    stale.status = WakeupStatus.ORPHANED
                    stale.updated_at = utcnow()
                    await uow.wakeups.update(stale)
                if pending:
                    await uow.commit()
                return None

            # Usually there is a pending wake to merge into. When there is not — the run
            # outlived its wake row — the cause is still recorded against the run, and the
            # re-evaluation at the end of the run is what makes sure it is not lost.
            target = pending[0] if pending else None
            if target is not None:
                target.source = stronger_source(target.source, source)
                target.reason = merge_causes(target.reason, source, reason)
                target.updated_at = utcnow()
                await uow.wakeups.update(target)

            # The individual cause is kept as its own row. The merged reason says *what*
            # the agent is owed; these rows say *when each cause arrived*, which is what
            # tells us afterwards whether a cause made it into the prompt or missed it.
            await uow.wakeups.add(
                WakeupRequest(
                    project_id=run.project_id,
                    marius_id=marius_id,
                    task_id=task_id,
                    source=source,
                    reason=reason,
                    status=WakeupStatus.COALESCED,
                    run_id=run.id,
                    created_at=utcnow(),
                )
            )

            # A run that has not started yet has no prompt: fold the cause into the run
            # itself so the packet the agent eventually reads names all of them
            # (quickstart scenario 4 step 2). Once it is running the prompt is already out
            # — that cause is handled by the re-evaluation when the run ends (step 3).
            if run.status == RunStatus.QUEUED and target is not None:
                run.wake_source = target.source
                run.trigger_detail = target.reason
                await uow.runs.update(run)

            await uow.commit()
            return run.id

    async def _open_run(
        self,
        marius_id: UUID,
        task_id: UUID,
        source: WakeSource,
        reason: str | None,
        continuation_attempt: int,
    ) -> UUID:
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
            # The wake goes in first: it is the row whose index arbitrates the race, and
            # its rejection is the one the caller knows how to recover from.
            await uow.wakeups.add(
                WakeupRequest(
                    project_id=task.project_id,
                    marius_id=marius_id,
                    task_id=task_id,
                    source=source,
                    reason=reason,
                    status=WakeupStatus.DISPATCHED,
                    run_id=run.id,
                    created_at=utcnow(),
                )
            )
            await uow.runs.add(run)
            await uow.commit()
            return run.id

    def _spawn(self, run_id: UUID, marius_id: UUID, task_id: UUID) -> None:
        bg = asyncio.create_task(self._execute_run(run_id, marius_id, task_id))
        self._bg.add(bg)
        bg.add_done_callback(self._bg.discard)

    async def drain(self, *, wait_seconds: float = 5.0) -> None:
        """Wait for every in-flight run to finish.

        Wakes are fire-and-forget by design, which leaves background work still writing
        after the call that started it returned. Anything that tears the database down —
        shutdown, or a test resetting the schema — has to wait for that work first, or it
        races the writes it is about to delete.

        Gives up rather than hanging forever if a run refuses to finish: this is a
        courtesy before teardown, not a guarantee.
        """
        while self._bg:
            pending = set(self._bg)
            done, _ = await asyncio.wait(pending, timeout=wait_seconds)
            if not done:
                return

    # -------------------------------------------------------------- run executor

    async def _execute_run(self, run_id: UUID, marius_id: UUID, task_id: UUID) -> None:
        try:
            await self._do_execute_run(run_id)
        except Exception:  # pragma: no cover - defensive
            logger.exception("run %s crashed", run_id)
        finally:
            # Release the pair whatever happened — including a cancellation, which is what
            # a container being told to stop looks like from in here. Leaving either half
            # behind wedges this agent out of this task permanently.
            await self._release_pair(run_id)
        # Both of these may enqueue, so they run only after the pair is free.
        await self._rewake_for_absorbed_causes(run_id, marius_id, task_id)
        await self._maybe_self_wake(run_id)

    async def _release_pair(self, run_id: UUID) -> None:
        """Give the (agent, task) pair back: settle the wake, and the run if it never was.

        A run that is still *running* here never reached ``_finalise`` — the turn was
        cancelled out from under it, which in practice means the process was told to stop
        mid-turn. Saying so ("stopped") is both true and what frees the pair; leaving it
        *running* would mean the next comment on that task, forever after, folds into a
        turn nobody is driving.

        A process killed outright gets no chance to run this at all, and its run does stay
        *running*. Reclaiming those needs a watchdog that can tell "crashed" from "slow" —
        that is Story 6 (FR-068), not something to guess at here.
        """
        async with self._uow() as uow:
            run = await uow.runs.get(run_id)
            if run is None or run.marius_id is None or run.task_id is None:
                return
            for w in await uow.wakeups.list_active_for(run.marius_id, run.task_id):
                if w.run_id != run_id:
                    continue
                w.status = WakeupStatus.DONE
                w.updated_at = utcnow()
                await uow.wakeups.update(w)
            if run.status in ACTIVE_RUN_STATUSES:
                run.status = RunStatus.STOPPED
                run.error = run.error or "máy chủ dừng giữa lượt chạy"
                run.finished_at = utcnow()
                await uow.runs.update(run)
            await uow.commit()

    async def _rewake_for_absorbed_causes(
        self, run_id: UUID, marius_id: UUID, task_id: UUID
    ) -> None:
        """FR-050, last clause: a cause that landed mid-run is reconsidered when it ends.

        "The running turn absorbs it" must not quietly mean "it is dropped". A cause that
        arrived after the prompt was built was never shown to the agent — if nothing looks
        again, a question asked one second too late is simply never answered.
        """
        async with self._uow() as uow:
            run = await uow.runs.get(run_id)
            if run is None:
                return
            absorbed = await uow.wakeups.list_coalesced_into(run_id)

        started = run.started_at
        owed = [
            w
            for w in absorbed
            if started is None or (w.created_at is not None and w.created_at >= started)
        ]
        if not owed:
            return

        source = owed[0].source
        merged: str | None = None
        for w in owed:
            source = stronger_source(source, w.source)
            merged = merge_causes(merged, w.source, w.reason)
        logger.info("re-waking %s for %d cause(s) absorbed mid-run", marius_id, len(owed))
        await self.enqueue(
            marius_id=marius_id, task_id=task_id, source=source, reason=merged
        )

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
            directory, self_role = await self._project_directory(uow, task.project_id, marius)
            new_messages = await self._new_messages(uow, task, marius)
            workspace = await uow.workspaces.get(marius.workspace_id)
            project = await uow.projects.get(task.project_id)
            # FR-009: only the APPROVED version rides the packet. A brief still under
            # review is a proposal — acting on it would make the approval gate cosmetic.
            brief = (
                await uow.project_contexts.get_approved(task.project_id)
                if task.project_id
                else None
            )

            prompt = build_wake_prompt(
                _wake_context(
                    run,
                    marius,
                    task,
                    directory,
                    self_role,
                    new_messages,
                    workspace,
                    project,
                    brief,
                )
            )

            # Keep the exact packet that went out. Until now nothing recorded what an
            # agent was actually told, so "why did it do that?" could only ever be
            # answered by guessing at what the builder would have produced — and the
            # answer changes with every deploy. The column was always meant for this.
            for pending in await uow.wakeups.list_active_for(marius.id, task.id):
                if pending.run_id != run_id:
                    continue
                pending.prompt = prompt
                pending.updated_at = utcnow()
                await uow.wakeups.update(pending)

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
            assistant_parts: list[str] = []

            async def _emit(event_type: str, payload: dict) -> None:
                """Persist a durable event, stream it on the run bus, and tee it to the Room.

                The Room-facing tee carries the event's own ``(_run_id, _seq)`` so a client
                that both backfills the durable history and replays the SSE backlog can
                de-duplicate the overlap by identity (#113)."""
                nonlocal seq
                seq += 1
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
                await self._tee_task(
                    task.id, event_type, {**payload, "_run_id": str(run_id), "_seq": seq}
                )

            async def _flush_assistant() -> None:
                """Coalesce buffered assistant deltas into ONE durable ``assistant.message``.

                Deltas themselves are never stored/teed (they'd flood the Room), so without
                this the Room stays empty of the agent's actual words. Flushing before every
                non-delta event (and at turn end) keeps the text↔tool interleaving in order."""
                if not assistant_parts:
                    return
                text = "".join(assistant_parts)
                assistant_parts.clear()
                if text.strip():
                    await _emit(
                        "assistant.message",
                        {"text": text, "marius_id": str(marius.id)},
                    )

            async def on_event(event_type: str, payload: dict) -> None:
                nonlocal seq
                if event_type == "assistant.delta":
                    # Accumulate the "thinking" text; stream it on the per-run bus only (live
                    # typing effect), never durable/teed — it is coalesced at flush time.
                    assistant_parts.append(str(payload.get("text") or payload.get("delta") or ""))
                    seq += 1
                    await self._bus.publish(
                        run_id, {"seq": seq, "type": event_type, "payload": payload}
                    )
                    return
                # Any non-delta event closes the current thought: flush it first so the
                # coalesced message lands BEFORE this event (correct interleaving).
                await _flush_assistant()
                await _emit(event_type, payload)

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

            # Flush any trailing "thinking" the turn ended without punctuating (no tool /
            # completed event after the last delta) so its text is not lost (#113).
            await _flush_assistant()

            await self._finalise(uow, run, task, marius, session, result)

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
        # COMPLETED or not — means the agent runtime reached back, so the agent is free again:
        # back to ONLINE (last_seen_at just bumped = a fresh signal) and the in-flight turn is
        # cleared. HUNG is reserved for the watchdog (a turn that went silent), never a
        # non-COMPLETED status — otherwise a task that simply failed or timed out would strand
        # the agent "offline" forever (#82 liveness fix).
        marius.liveness = Liveness.ONLINE
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

    async def _project_directory(
        self, uow, project_id: UUID | None, marius: Marius  # noqa: ANN001
    ) -> tuple[list[tuple[Marius, Role | None]], Role | None]:
        """Project participants (granted seats) paired with their PROJECT role, plus the
        woken agent's own role.

        Project-scoped (§3.2): the directory is the seat-holders of THIS project — resolved
        via `seat_grants.list_by_project` + `roles.list_by_project` — NOT every agent in the
        workspace. Each agent's role comes from `SeatGrant.role_key → Role`, never the empty
        workspace-level `Marius.role`.
        """
        if project_id is None:
            return [], None
        grants = await uow.seat_grants.list_by_project(project_id)
        roles = {r.key: r for r in await uow.roles.list_by_project(project_id)}
        role_by_marius: dict[UUID, Role | None] = {}
        member_ids: list[UUID] = []
        for g in grants:
            if g.status != SeatGrantStatus.GRANTED or g.marius_id is None:
                continue
            if g.marius_id not in role_by_marius:
                member_ids.append(g.marius_id)
            role_by_marius[g.marius_id] = roles.get(g.role_key)
        members = {m.id: m for m in await uow.mariuses.list_by_ids(member_ids)}
        directory = [
            (members[mid], role_by_marius.get(mid))
            for mid in member_ids
            if mid in members
        ]
        return directory, role_by_marius.get(marius.id)

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
    directory: Sequence[tuple[Marius, Role | None]],
    self_role: Role | None,
    messages: Sequence[Comment],
    workspace: Workspace | None = None,
    project: Project | None = None,
    brief: ProjectContext | None = None,
) -> WakeContext:
    dir_entries = [
        DirectoryEntry(
            name=m.name,
            role=(role.title if role else ""),
            role_description=(role.description if role else ""),
            skills=list(m.skills),
            liveness=str(m.liveness),
        )
        for (m, role) in directory
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
        self_role=(self_role.title if self_role else ""),
        self_role_description=(self_role.description if self_role else ""),
        project_brief=(
            ProjectBrief(
                objective=brief.objective,
                background=brief.background,
                constraints=brief.constraints,
                scope=brief.scope,
                principles=brief.principles,
            )
            if brief
            else None
        ),
        workspace_name=workspace.name if workspace else "",
        project_name=project.name if project else "",
        credential_file=(
            credential_file_for(marius, workspace.name) if workspace else None
        ),
    )
