"""Commission use case (LLD §2.13) — leader-mediated task shaping, fully async.

A commission is a chat between the Patron and a project's **Leader agent** that shapes
exactly one Task: a fresh ``draft`` (new task) or an existing confirmed task (an edit).
Because the Leader is an agent, every turn is asynchronous — the service wakes the Leader
through the :class:`WakeEngine` and surfaces progress via ``leader_state``:

  - **thinking** — a Leader turn is enqueued/running.
  - **waiting** — the Leader answered; awaiting the Patron.
  - **leader_offline** — the Leader was offline when a turn was requested; the turn is
    *queued* on the open session and **drained** (re-enqueued) once the Leader comes online.

``confirm`` flips the draft ``draft → todo`` and wakes the project's seated workers so the
freshly shaped task gets picked up.
"""

from __future__ import annotations

from collections.abc import Sequence
from uuid import UUID

from armarius.application.use_cases.types import UowFactory
from armarius.application.use_cases.wake_engine import WakeEngine
from armarius.domain.entities.commission import (
    CommissionSession,
    LeaderState,
)
from armarius.domain.entities.marius import Liveness
from armarius.domain.entities.run import WakeSource
from armarius.domain.entities.seat_grant import SeatGrantStatus
from armarius.domain.entities.task import Task, TaskStatus
from armarius.shared.clock import utcnow

# A Leader can run a turn unless it is offline/hung; otherwise the turn is queued.
_AVAILABLE = {Liveness.ONLINE, Liveness.WORKING, Liveness.IDLE, Liveness.CHECKING}

_LEADER_ROLE_KEY = "leader"


class CommissionError(Exception):
    """Raised on an illegal commission operation (e.g. no Leader seated)."""


class CommissionService:
    def __init__(self, uow_factory: UowFactory, wake_engine: WakeEngine) -> None:
        self._uow = uow_factory
        self._wake = wake_engine

    # ── open a commission ────────────────────────────────────────────────────────
    async def commission(
        self,
        *,
        project_id: UUID,
        message: str,
        title: str | None = None,
        created_by_user_id: str | None = None,
    ) -> CommissionSession:
        """Start shaping a NEW task: create a `draft` Task + an open CommissionSession,
        then wake the Leader (or queue the turn if the Leader is offline)."""
        now = utcnow()
        async with self._uow() as uow:
            project = await uow.projects.get(project_id)
            if project is None:
                raise LookupError("project not found")
            leader_id = await self._leader_of(uow, project_id)
            available = await self._leader_available(uow, leader_id)

            draft = Task(
                project_id=project_id,
                title=title or (message[:120] if message else "Untitled draft"),
                description=None,
                status=TaskStatus.DRAFT,
                created_by_user_id=created_by_user_id,
                created_at=now,
                updated_at=now,
            )
            await uow.tasks.add(draft)

            session = CommissionSession(
                project_id=project_id,
                leader_marius_id=leader_id,
                task_id=draft.id,
                transcript=[{"role": "patron", "text": message}],
                leader_state=(
                    LeaderState.THINKING if available else LeaderState.LEADER_OFFLINE
                ),
                created_at=now,
                updated_at=now,
            )
            await uow.commissions.add(session)
            await uow.commit()

        if available:
            await self._wake_leader(session)
        return session

    async def edit(
        self, *, task_id: UUID, message: str
    ) -> CommissionSession:
        """Open a commission on an EXISTING task (a confirmed task being reshaped)."""
        now = utcnow()
        async with self._uow() as uow:
            task = await uow.tasks.get(task_id)
            if task is None:
                raise LookupError("task not found")
            if task.project_id is None:
                raise CommissionError("task has no project")
            leader_id = await self._leader_of(uow, task.project_id)
            available = await self._leader_available(uow, leader_id)

            session = CommissionSession(
                project_id=task.project_id,
                leader_marius_id=leader_id,
                task_id=task_id,
                transcript=[{"role": "patron", "text": message}],
                leader_state=(
                    LeaderState.THINKING if available else LeaderState.LEADER_OFFLINE
                ),
                created_at=now,
                updated_at=now,
            )
            await uow.commissions.add(session)
            await uow.commit()

        if available:
            await self._wake_leader(session)
        return session

    # ── refine / confirm / abandon ───────────────────────────────────────────────
    async def refine(self, session_id: UUID, message: str) -> CommissionSession:
        """Add a Patron turn to an open commission and wake the Leader again."""
        now = utcnow()
        async with self._uow() as uow:
            session = await self._open_session(uow, session_id)
            session.transcript = [*session.transcript, {"role": "patron", "text": message}]
            available = await self._leader_available(uow, session.leader_marius_id)
            session.leader_state = (
                LeaderState.THINKING if available else LeaderState.LEADER_OFFLINE
            )
            session.updated_at = now
            await uow.commissions.update(session)
            await uow.commit()

        if available:
            await self._wake_leader(session)
        return session

    async def confirm(self, session_id: UUID) -> CommissionSession:
        """Lock the proposal: draft `draft → todo` and wake the project's seated workers."""
        now = utcnow()
        worker_ids: list[UUID] = []
        task_id: UUID | None = None
        async with self._uow() as uow:
            session = await self._open_session(uow, session_id)
            session.confirm()  # OPEN → CONFIRMED (raises CommissionError otherwise)
            session.leader_state = LeaderState.WAITING
            session.updated_at = now

            if session.task_id is not None:
                task = await uow.tasks.get(session.task_id)
                if task is not None and task.status == TaskStatus.DRAFT:
                    task.transition_to(TaskStatus.TODO, now)
                    task.updated_at = now
                    await uow.tasks.update(task)
                    task_id = task.id
                    worker_ids = await self._seated_workers(
                        uow, task.project_id, leader_id=session.leader_marius_id
                    )
            await uow.commissions.update(session)
            await uow.commit()

        # A confirmed draft is now on the board — wake the workers who can pick it up.
        if task_id is not None:
            for worker_id in worker_ids:
                await self._wake.enqueue(
                    marius_id=worker_id,
                    task_id=task_id,
                    source=WakeSource.COMMISSION,
                    reason="a task was just published to the board",
                )
        return session

    async def abandon(self, session_id: UUID) -> CommissionSession:
        """Drop an open commission; cancel its draft task if it was never confirmed."""
        now = utcnow()
        async with self._uow() as uow:
            session = await self._open_session(uow, session_id)
            session.abandon()  # OPEN → ABANDONED
            session.updated_at = now
            if session.task_id is not None:
                task = await uow.tasks.get(session.task_id)
                if task is not None and task.status == TaskStatus.DRAFT:
                    task.transition_to(TaskStatus.CANCELLED, now)
                    task.updated_at = now
                    await uow.tasks.update(task)
            await uow.commissions.update(session)
            await uow.commit()
            return session

    # ── drain queued turns when a Leader comes online ────────────────────────────
    async def on_leader_online(self, leader_marius_id: UUID) -> int:
        """A Leader just came online → re-enqueue every turn queued while it was offline.

        Returns the number of commissions drained. Idempotent: a session already THINKING
        (not queued) is left untouched.
        """
        now = utcnow()
        to_wake: list[CommissionSession] = []
        async with self._uow() as uow:
            open_sessions = await uow.commissions.list_open_by_leader(leader_marius_id)
            for session in open_sessions:
                if session.leader_state != LeaderState.LEADER_OFFLINE:
                    continue
                session.leader_state = LeaderState.THINKING
                session.updated_at = now
                await uow.commissions.update(session)
                to_wake.append(session)
            if to_wake:
                await uow.commit()

        for session in to_wake:
            await self._wake_leader(session)
        return len(to_wake)

    # ── queries ──────────────────────────────────────────────────────────────────
    async def get(self, session_id: UUID) -> CommissionSession | None:
        async with self._uow() as uow:
            return await uow.commissions.get(session_id)

    # ── helpers ──────────────────────────────────────────────────────────────────
    async def _wake_leader(self, session: CommissionSession) -> None:
        if session.leader_marius_id is None or session.task_id is None:
            return
        await self._wake.enqueue(
            marius_id=session.leader_marius_id,
            task_id=session.task_id,
            source=WakeSource.COMMISSION,
            reason="shape this task with the patron",
        )

    async def _open_session(self, uow, session_id: UUID) -> CommissionSession:  # noqa: ANN001
        session = await uow.commissions.get(session_id)
        if session is None:
            raise LookupError("commission session not found")
        return session

    async def _leader_of(self, uow, project_id: UUID) -> UUID:  # noqa: ANN001
        grants = await uow.seat_grants.list_by_project(project_id)
        leader = next(
            (
                g
                for g in grants
                if g.status == SeatGrantStatus.GRANTED
                and g.role_key == _LEADER_ROLE_KEY
                and g.marius_id is not None
            ),
            None,
        )
        if leader is None:
            raise CommissionError("no Leader is seated on this project")
        return leader.marius_id

    async def _leader_available(self, uow, leader_id: UUID) -> bool:  # noqa: ANN001
        leader = await uow.mariuses.get(leader_id)
        return leader is not None and leader.liveness in _AVAILABLE

    async def _seated_workers(
        self, uow, project_id: UUID | None, *, leader_id: UUID | None  # noqa: ANN001
    ) -> Sequence[UUID]:
        if project_id is None:
            return []
        grants = await uow.seat_grants.list_by_project(project_id)
        seen: list[UUID] = []
        for g in grants:
            if (
                g.status == SeatGrantStatus.GRANTED
                and g.role_key != _LEADER_ROLE_KEY
                and g.marius_id is not None
                and g.marius_id != leader_id
                and g.marius_id not in seen
            ):
                seen.append(g.marius_id)
        return seen
