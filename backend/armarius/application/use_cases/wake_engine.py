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
from armarius.application.ports.unit_of_work import UnitOfWork
from armarius.application.ports.work_packet import SkillBundle, WorkPacket
from armarius.application.ports.workspace_trace import (
    WorkspaceTracePublisher,
    announce_run_state,
)
from armarius.application.use_cases.onboarding import credential_file_for
from armarius.application.use_cases.seats import holds_the_leader_seat
from armarius.application.use_cases.skills import SkillService
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
from armarius.domain.entities.session import AgentTaskSession
from armarius.domain.entities.task import Task, TaskStatus
from armarius.domain.entities.wakeup import (
    WakePairBusyError,
    WakeupRequest,
    WakeupStatus,
)
from armarius.domain.entities.workspace import Project, Workspace
from armarius.domain.services.project_rules import ProjectClosed, is_closed
from armarius.domain.services.wake_coalesce import merge_reasons, stronger_source
from armarius.domain.services.wake_policy import WakeRole, decide_self_wake, may_wake
from armarius.domain.services.wake_prompt import (
    DirectoryEntry,
    ProjectBrief,
    ThreadMessage,
    WakeAudience,
    WakeContext,
    build_wake_prompt,
)
from armarius.domain.services.wake_reason import WakeReason, render_en
from armarius.domain.services.wake_reason import reason as wake_reason
from armarius.shared.background import settle
from armarius.shared.clock import utcnow
from armarius.shared.errors import NotFound
from armarius.shared.logging import get_logger

logger = get_logger(__name__)

_BLOCK_REASON_STATUSES = {TaskStatus.BLOCKED, TaskStatus.BACKLOG}
#: How much of a crash's description is kept on the run. Enough to name what happened
#: without letting one runaway message dominate the row.
_MAX_ERROR_CHARS = 500


def _describe(exc: BaseException) -> str:
    """Name what killed a turn in one line, without the driver's own paperwork.

    A database error stringifies into several lines: the message, then the statement that
    failed, then a documentation link. Only the first says anything a reader of the run
    needs — and the rest would put query text and column names on a screen the patron sees.
    """
    lines = str(exc).strip().splitlines()
    return f"{type(exc).__name__}: {lines[0].strip() if lines else ''}"[:_MAX_ERROR_CHARS]


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
        workspace_trace: WorkspaceTracePublisher | None = None,
        skills: SkillService | None = None,
    ) -> None:
        self._uow = uow_factory
        self._registry = registry
        self._bus = event_bus
        # Only `compose_packet` needs it — the road that hands the whole packet over at
        # once. Optional so the engine can still be built for the paths that never compose
        # one; an engine without it composes a packet with no skills in it, which is the
        # truth about an engine that was not given any way to find them.
        self._skills = skills
        # Optional per-task tee: mirrors run events onto the `task:{id}` SSE channel (§8.1).
        self._task_trace = task_trace
        # Optional workspace-wide tee: announces the run's *lifecycle* (not its content) so a
        # screen that watches an agent rather than a run has something to listen to (FR-080).
        self._workspace_trace = workspace_trace
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
        reason: WakeReason | None = None,
        continuation_attempt: int = 0,
    ) -> UUID | None:
        """Queue a task-scoped wake. Returns the run id (the existing one if coalesced).

        FR-050 in one place: at most one pending wake and one live run per *(agent, task)*.
        The decision is made from the database, not from a dictionary in this process —
        which is what makes it survive a restart and hold across more than one worker.

        The lock below still helps (it keeps the common case from doing wasted work) but it
        is no longer what guarantees the invariant. The partial unique index is. If two
        callers race past the lock, the loser is told the pair is busy and folds in.

        Returns ``None`` when the cause is not one this recipient's role may be woken for
        (FR-048a). Refusing the wake rather than raising is deliberate: the mistake is in
        whoever booked the wake, and taking down the patron's own action — the comment they
        posted, the task they moved — would punish the wrong party for it. The refusal is
        on the record and in the log instead.
        """
        await self._refuse_if_closed(task_id)
        async with self._lock:
            for attempt in (0, 1):
                # One transaction per attempt, and the eligibility check is inside it.
                # Read in a transaction of its own the answer is only a snapshot: the
                # leader seat can be revoked between the check and the insert, and the
                # wake then goes out approved by a roster that no longer exists (T198).
                async with self._uow() as uow:
                    if not await self._cause_fits_the_recipient(
                        uow, marius_id, task_id, source, reason
                    ):
                        # The refused wake row is the only thing this transaction wrote.
                        await uow.commit()
                        return None
                    folded = await self._fold_into_pending(
                        uow, marius_id, task_id, source, reason
                    )
                    if folded is not None:
                        await uow.commit()
                        logger.info("wake coalesced into run %s (%s)", folded, source)
                        return folded
                    try:
                        opened = await self._open_run(
                            uow, marius_id, task_id, source, reason, continuation_attempt
                        )
                        await uow.commit()
                    except WakePairBusyError:
                        if attempt == 0:
                            continue  # someone opened a run between our read and our write
                        raise
                break
            else:  # pragma: no cover - the loop always returns or breaks
                raise RuntimeError("wake enqueue did not settle")

        # Both of these are after the commit on purpose: one announces a run that exists,
        # the other starts driving it.
        run, marius = opened
        await self.announce_run(run, marius)
        self._spawn(run.id, marius_id, task_id)
        return run.id

    async def _refuse_if_closed(self, task_id: UUID) -> None:
        """FR-005 — a closed project wakes nobody, through any door.

        This sits in front of every wake rather than beside each caller because the doors
        are not all on the board. Filtering the stall sweep stops the loop that walks
        `tasks`; it does nothing about the hung-run reaper, which walks `runs` and re-wakes
        the assignee of a run that was still live when the patron closed the project. Two
        loops, two tables, one rule — so the rule goes where both of them pass.

        Refusing loudly rather than quietly returning: the patron's own manual wake button
        comes through here too, and a button that silently does nothing is worse than one
        that says why.
        """
        async with self._uow() as uow:
            task = await uow.tasks.get(task_id)
            if task is None or task.project_id is None:
                return
            project = await uow.projects.get(task.project_id)
            if project is not None and is_closed(project.status):
                raise ProjectClosed("project_closed_no_wake")

    async def _cause_fits_the_recipient(
        self,
        uow: UnitOfWork,
        marius_id: UUID,
        task_id: UUID,
        source: WakeSource,
        reason: WakeReason | None,
    ) -> bool:
        """FR-048a — hold the two closed cause lists to the wake actually being sent.

        The hats are read from the work, not from the agent record: whoever the task is
        assigned to is its worker, and whoever holds the project's leader seat is its
        Leader. One agent can be both at once, and then both sets of causes reach it.

        Takes the caller's transaction rather than opening one, so the roster it approves
        the wake against is the roster the run is inserted under. The two used to be
        separate reads with a gap between them, and a seat revoked inside that gap let an
        already-approved wake through (T198).

        A refused wake is written down as a wake — same table, its own status — because the
        thing worth catching is not the single dropped call but the pattern: a cause added
        without deciding who it may wake shows up here as a row nobody expected. The row is
        left for the caller to commit, since on this path it is all the transaction has.
        """
        task = await uow.tasks.get(task_id)
        if task is None:
            return True  # the run open below will fail on it and say so properly
        roles: set[WakeRole] = set()
        if task.assigned_marius_id == marius_id:
            roles.add(WakeRole.WORKER)
        if task.project_id is not None and await holds_the_leader_seat(
            uow, task.project_id, marius_id
        ):
            roles.add(WakeRole.LEADER)
        if may_wake(source, roles=roles):
            return True

        causes = merge_reasons([], source, reason)
        logger.warning(
            "wake refused: %s may not wake %s on task %s (roles: %s)",
            source,
            marius_id,
            task_id,
            ", ".join(sorted(str(r) for r in roles)) or "none",
        )
        await uow.wakeups.add(
            WakeupRequest(
                project_id=task.project_id,
                marius_id=marius_id,
                task_id=task_id,
                source=source,
                causes=causes,
                reason=render_en(causes),
                status=WakeupStatus.REFUSED,
                created_at=utcnow(),
            )
        )
        return False

    async def _fold_into_pending(
        self,
        uow: UnitOfWork,
        marius_id: UUID,
        task_id: UUID,
        source: WakeSource,
        reason: WakeReason | None,
    ) -> UUID | None:
        """Merge one more cause into the wake this pair already owes, if there is one.

        Returns the run id the cause was folded into, or ``None`` when the pair is free.

        The question asked here is **"is a run still holding this pair?"**, not "is there a
        pending wake row?". Those come apart: a process stopped mid-turn closes its wake on
        the way out but cannot finalise the run it was driving. Keying off the wake row
        would then read the pair as free, try to open a second run, and be refused by the
        index — turning an ordinary restart into an error on the next comment.

        Runs in the caller's transaction: retiring a leftover row and opening the run that
        replaces it are one decision, and a crash between them is what leaves the pair
        wedged.
        """
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
            return None

        # Usually there is a pending wake to merge into. When there is not — the run
        # outlived its wake row — the cause is still recorded against the run, and the
        # re-evaluation at the end of the run is what makes sure it is not lost.
        target = pending[0] if pending else None
        if target is not None:
            target.source = stronger_source(target.source, source)
            target.causes = merge_reasons(target.causes, source, reason)
            target.reason = render_en(target.causes)
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
                causes=merge_reasons([], source, reason),
                reason=render_en(merge_reasons([], source, reason)),
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
            run.trigger_causes = list(target.causes)
            run.trigger_detail = target.reason
            await uow.runs.update(run)

        return run.id

    async def _open_run(
        self,
        uow: UnitOfWork,
        marius_id: UUID,
        task_id: UUID,
        source: WakeSource,
        reason: WakeReason | None,
        continuation_attempt: int,
    ) -> tuple[Run, Marius]:
        """Write the wake and the run it dispatches, in the caller's transaction.

        Returns both rather than the id alone because the announcement needs the agent, and
        it is made **after** the commit — announcing a run that a rollback then erased is
        how a board grows a card for work that never started.
        """
        task = await uow.tasks.get(task_id)
        marius = await uow.mariuses.get(marius_id)
        if task is None or marius is None:
            raise NotFound("task_or_agent_not_found")
        causes = merge_reasons([], source, reason)
        run = Run(
            project_id=task.project_id,
            marius_id=marius_id,
            task_id=task_id,
            adapter_type=marius.adapter_type,
            wake_source=source,
            trigger_causes=causes,
            trigger_detail=render_en(causes),
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
                causes=causes,
                reason=render_en(causes),
                status=WakeupStatus.DISPATCHED,
                run_id=run.id,
                created_at=utcnow(),
            )
        )
        await uow.runs.add(run)
        return run, marius

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
        """Drive one run to its end, and hand the pair back whatever happens.

        Nothing may leave this method. It is the body of a bare background task, so an
        exception raised anywhere in here reaches no caller: the run stays open, the pair
        stays held, every later cause folds into a turn nobody is driving, and the only
        trace is a warning at interpreter shutdown. The cleanup below is itself a write,
        and a write is exactly the thing that can be refused — so it is retried and its
        failure is spoken, rather than left to become silence (see ``settle``).
        """
        cause: str | None = None
        try:
            await self._do_execute_run(run_id)
        except Exception as exc:
            logger.exception("run %s crashed", run_id)
            cause = _describe(exc)
        finally:
            # Release the pair whatever happened — including a cancellation, which is what
            # a container being told to stop looks like from in here. Leaving either half
            # behind wedges this agent out of this task permanently.
            await self._release_pair(run_id, cause=cause)
        # Both of these may enqueue, so they run only after the pair is free. Losing either
        # loses work with nobody the wiser: a cause that arrived mid-turn is never shown to
        # anyone, or a turn that owed a continuation never gets one. Repeating an `enqueue`
        # is safe because nothing it does after its commit can throw — see `announce_run`,
        # which is what makes that true rather than merely hoped for.
        await settle(
            f"re-wake run {run_id} for the causes it absorbed",
            lambda: self._rewake_for_absorbed_causes(run_id, marius_id, task_id),
        )
        await settle(
            f"decide the follow-up wake after run {run_id}",
            lambda: self._maybe_self_wake(run_id),
        )

    async def conclude_run(
        self,
        run_id: UUID,
        *,
        status: RunStatus,
        error: str | None = None,
        usage: dict | None = None,
    ) -> None:
        """Close a run that was carried out somewhere this process cannot watch (FR-030a).

        The same ending as a run driven in-process, reached from the other direction. A run on
        somebody's machine produces no return value here — the machine reports it — so this is
        where the tail of ``_execute_run`` is reused rather than written a second time. Two
        endings would be two answers to *what happens after a run*, and the follow-up wake is
        precisely the half that would go missing from the second one.

        **The follow-up wake is the point.** A run ending is not the same as a task being
        finished with, and FR-030a names the hole exactly: a run ends cleanly, the task is still
        in progress, and nothing is scheduled to look at it again. The sweep catches that, but
        late — it is the backstop, not the answer. ``_maybe_self_wake`` is the answer, and it
        runs here for the same reason it runs after an in-process turn.

        Reporting twice is not an error. A machine whose reply went missing calls again, and the
        second call finds the run already closed and leaves it alone — repeating the finalise
        would spend a continuation attempt the first call already spent.
        """
        async with self._uow() as uow:
            run = await uow.runs.get(run_id)
            if run is None or run.status not in ACTIVE_RUN_STATUSES:
                return
            task = await uow.tasks.get(run.task_id) if run.task_id else None
            marius = await uow.mariuses.get(run.marius_id) if run.marius_id else None
            if task is None or marius is None:
                return
            session = await uow.sessions.get_for(marius.id, marius.adapter_type, task.id)
            marius_id, task_id = marius.id, task.id
            await self._finalise(
                uow,
                run,
                task,
                marius,
                session,
                ExecResult(status=status, error=error, usage=usage or {}),
            )

        # After the finalise and in this order, exactly as an in-process run ends: the pair is
        # handed back first because both of the calls after it may enqueue, and enqueueing
        # against a pair this run still holds folds the new wake into the turn that just ended.
        await self._release_pair(run_id, cause=error)
        await settle(
            f"re-wake run {run_id} for the causes it absorbed",
            lambda: self._rewake_for_absorbed_causes(run_id, marius_id, task_id),
        )
        await settle(
            f"decide the follow-up wake after run {run_id}",
            lambda: self._maybe_self_wake(run_id),
        )

    async def _release_pair(self, run_id: UUID, *, cause: str | None = None) -> None:
        """Hand the (agent, task) pair back, retrying a lost write race.

        Retried rather than attempted once because this write contends like any other:
        wakes are fire-and-forget, so two runs ending at the same instant is ordinary, and
        the loser is refused a lock it could have taken a moment later. Unretried, that
        refusal used to escape into a background task nobody awaits — the pair stayed held
        and no error surfaced anywhere. Reclaiming a pair whose release never landed at all
        is the hung-run watchdog's job (FR-062), on its own much slower clock.

        ``cause`` is what killed the turn, when something did.
        """
        await settle(
            f"hand back the pair held by run {run_id}",
            lambda: self._release_pair_once(run_id, cause),
        )

    async def _release_pair_once(self, run_id: UUID, cause: str | None) -> None:
        """Give the (agent, task) pair back: settle the wake, and the run if it never was.

        A run that is still *running* here never reached ``_finalise`` — the turn was
        cancelled out from under it, which in practice means the process was told to stop
        mid-turn. Saying so ("stopped") is both true and what frees the pair; leaving it
        *running* would mean the next comment on that task, forever after, folds into a
        turn nobody is driving.

        A process killed outright gets no chance to run this at all, and its run does stay
        *running*. Reclaiming those needs a watchdog that can tell "crashed" from "slow" —
        that is Story 6 (FR-068), not something to guess at here.

        Safe to run twice: everything it decides it re-reads first, so a second pass over a
        pair already handed back finds nothing left to do and announces nothing again.
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
            unsettled = run.status in ACTIVE_RUN_STATUSES
            if unsettled:
                # *Failed* when the turn blew up, *stopped* when it was cut short. Both free
                # the pair and both lead to the same continuation, but only one of them is
                # true — and this row is the only place anyone can read afterwards which it
                # was. Recording a crash as "the server stopped" is how a real fault ends up
                # looking like an ordinary restart.
                run.status = RunStatus.FAILED if cause else RunStatus.STOPPED
                run.error = run.error or cause or "máy chủ dừng giữa lượt chạy"
                run.finished_at = utcnow()
                await uow.runs.update(run)
            await uow.commit()
            # Only when this call is what ended the run. The ordinary path already announced
            # its own terminal status in `_finalise`, and repeating it here would put a second
            # identical event on the channel for every single run.
            if unsettled:
                marius = await uow.mariuses.get(run.marius_id)
                if marius is not None:
                    await self.announce_run(run, marius)

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

        logger.info("re-waking %s for %d cause(s) absorbed mid-run", marius_id, len(owed))
        # One call per cause rather than a pre-merged one. The first opens the run; the
        # rest fold into it through the very same coalescing path a live cause takes, which
        # is the path that already knows how to keep each cause exactly once and file the
        # wake under the strongest of them. Merging here as well would be a second
        # implementation of that rule, free to drift from the first.
        for w in owed:
            for cause in w.causes or [wake_reason(str(w.source))]:
                await self.enqueue(
                    marius_id=marius_id, task_id=task_id, source=w.source, reason=cause
                )

    # ------------------------------------------------------- the message and the packet

    async def _assemble(
        self,
        uow: UnitOfWork,
        run: Run,
        task: Task,
        marius: Marius,
        *,
        credential_hint: bool,
    ) -> str:
        """Gather what this wake has to say and write it out, in English (Constitution VII).

        One assembler for both roads, and that is the whole reason it is a method rather
        than a paragraph inside the run loop. The message is built from the agent's own
        instructions, the project's approved brief and the reason it was woken — three
        rules that live on this side and cannot be checked on the far one (FR-011a). Two
        assemblers would mean two answers to *what was this agent told*, and the answer
        would depend on which road the run happened to take.
        """
        directory, self_role = await self._project_directory(uow, task.project_id, marius)
        new_messages = await self._new_messages(uow, task, marius)
        workspace = await uow.workspaces.get(marius.workspace_id)
        project = await uow.projects.get(task.project_id) if task.project_id else None
        # FR-009: only the APPROVED version rides the packet. A brief still under
        # review is a proposal — acting on it would make the approval gate cosmetic.
        brief = (
            await uow.project_contexts.get_approved(task.project_id)
            if task.project_id
            else None
        )

        # Which set of extras this packet carries (FR-044a). Read off the work, the way
        # the cause guard reads it: whoever holds the task is its worker. An agent
        # wearing both hats gets the worker packet — it is the one doing the job.
        audience = (
            WakeAudience.WORKER
            if task.assigned_marius_id == marius.id
            else WakeAudience.LEADER
        )
        return build_wake_prompt(
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
                audience,
                credential_hint=credential_hint,
            )
        )

    async def compose_packet(self, run_id: UUID) -> WorkPacket | None:
        """Everything one run needs handed over in a single piece (FR-011, FR-011b).

        Called at the moment the work changes hands, not when it was queued: the message
        names the task's newest comments and its recorded next action, and a message built
        an hour early would describe a task nobody has since touched. `None` means this run
        cannot be described — no task, no agent, nothing to say — and a run nobody can
        describe is a run nobody can do.

        The skills come whole rather than as a list to fetch. An agent that has to go and
        collect them can start reading before they arrive, and then the first thing it does
        is the one thing it was not equipped for (FR-011c).

        No credential hint rides this packet: the run's credential is handed to the process
        itself, so there is no file to name (FR-014c).
        """
        async with self._uow() as uow:
            run = await uow.runs.get(run_id)
            if run is None:
                return None
            task = await uow.tasks.get(run.task_id) if run.task_id else None
            marius = await uow.mariuses.get(run.marius_id) if run.marius_id else None
            if task is None or marius is None:
                return None
            prompt = await self._assemble(uow, run, task, marius, credential_hint=False)

        return WorkPacket(prompt=prompt, skills=await self._bundles(marius))

    async def _bundles(self, marius: Marius) -> tuple[SkillBundle, ...]:
        """This agent's granted skills, whole, and **only** this agent's (FR-007b).

        Read off the agent rather than off the workplace it sits at. Several agents share
        one workplace, so a skill list gathered from the machine would be every agent's
        skills at once — which is the leak the per-run write exists to prevent, arriving
        one layer earlier where the write cannot see it.

        A path that could climb out of its own skill directory is refused, and the skill it
        belongs to is refused with it: the file tree of a skill can be edited by hand or
        pulled from a repository, so this is data from outside, and a half-written skill is
        worse than an absent one — the agent would read a SKILL.md whose companion files
        were silently dropped.
        """
        if self._skills is None:
            return ()
        bundles: list[SkillBundle] = []
        for skill in await self._skills.resolve(list(marius.skill_ids)):
            if not _is_safe_segment(skill.slug):
                logger.warning("skill %s has an unusable directory name", skill.id)
                continue
            files = {k: v for k, v in (skill.files or {}).items() if isinstance(v, str)}
            if not files:
                # An empty directory teaches an agent nothing and reads, to whoever opens
                # it, as a skill that failed to arrive.
                logger.warning("skill %s has no files to send", skill.id)
                continue
            if not all(_stays_inside(path) for path in files):
                logger.warning("skill %s has a path that leaves its own directory", skill.id)
                continue
            bundles.append(SkillBundle(name=skill.slug, files=files))
        return tuple(bundles)

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
            prompt = await self._assemble(uow, run, task, marius, credential_hint=True)

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
            await self.announce_run(run, marius)

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
        await self.announce_run(run, marius)

    async def _tee_task(self, task_id: UUID, event_type: str, payload: dict) -> None:
        """Mirror a run event onto the per-task SSE channel (no-op if not wired)."""
        if self._task_trace is not None:
            await self._task_trace.publish(task_id, event_type, payload)

    async def announce_run(self, run: Run, marius: Marius) -> None:
        """Announce a run's state on the workspace channel — see ``announce_run_state``.

        Best effort, deliberately: telling a screen must never break the thing it is
        telling about. Every one of these calls sits *after* the commit it reports, and in
        ``_open_run`` it sits before the background task that will actually drive the run —
        so a channel that threw used to leave a run committed as *queued* with nobody
        executing it, the pair held until the hung-run watchdog reclaimed it twelve minutes
        later. It also broke the one property retrying depends on: an ``enqueue`` that
        wrote its rows and then raised cannot be made right by calling it again, because
        the second call folds into the run the first one stranded.

        The hung-run reaper already works to this rule ("telling a screen matters less
        than saving the task"). What it costs is one run showing its previous status until
        the page is reloaded; what raising costs is work that stops.
        """
        try:
            await announce_run_state(self._workspace_trace, run, marius)
        except Exception:
            logger.exception("could not announce run %s on the workspace channel", run.id)

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
                reason=wake_reason(decision.code) if decision.code else None,
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
        workspace. Each agent's role comes from `SeatGrant.role_id → Role`, never the empty
        workspace-level `Marius.role`.
        """
        if project_id is None:
            return [], None
        grants = await uow.seat_grants.list_by_project(project_id)
        roles = {r.id: r for r in await uow.roles.list_by_project(project_id)}
        role_by_marius: dict[UUID, Role | None] = {}
        member_ids: list[UUID] = []
        for g in grants:
            if g.marius_id not in role_by_marius:
                member_ids.append(g.marius_id)
            role_by_marius[g.marius_id] = roles.get(g.role_id)
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
    audience: WakeAudience = WakeAudience.WORKER,
    *,
    credential_hint: bool = True,
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
        audience=audience,
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
        instructions=marius.instructions,
        credential_hint=credential_hint,
        credential_file=(
            credential_file_for(marius, workspace.name) if workspace else None
        ),
    )


# ── what may be written where (FR-011b) ──────────────────────────────────────────

_UNSAFE = {"", ".", ".."}


def _is_safe_segment(name: str) -> bool:
    """Whether `name` can be one directory, and only ever one directory."""
    return name not in _UNSAFE and "/" not in name and "\\" not in name and ":" not in name


def _stays_inside(path: str) -> bool:
    """Whether a skill file's relative path can only land inside its own directory.

    Checked segment by segment rather than by cleaning the string: cleaning answers *where
    would this end up*, which is the right question only if the answer is then compared
    against the root, and that comparison is the step everybody forgets. Asking whether any
    single step could climb, or start from the top, has no such second half.
    """
    if path.startswith("/") or path.startswith("\\") or ":" in path:
        return False
    parts = path.replace("\\", "/").split("/")
    return bool(parts) and all(_is_safe_segment(part) for part in parts)
