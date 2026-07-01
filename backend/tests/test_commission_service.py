"""CommissionService — async leader turns, draft→todo confirm, offline queue+drain (LLD §2.13).

Uses a recording stand-in for the WakeEngine so the tests assert *who gets woken* (and when
a turn is queued instead) without running any adapter.
"""

from __future__ import annotations

from uuid import UUID, uuid4

import pytest

from armarius.application.use_cases.commission import CommissionError, CommissionService
from armarius.application.use_cases.projects import ProjectService, RoleSpec
from armarius.domain.entities.commission import CommissionStatus, LeaderState
from armarius.domain.entities.marius import Liveness, Marius
from armarius.domain.entities.run import WakeSource
from armarius.domain.entities.task import TaskStatus
from armarius.domain.entities.workspace import Workspace
from tests.support.fakes import FakeUowFactory


class _RecordingWake:
    """Stand-in WakeEngine: records enqueue calls instead of running an adapter turn."""

    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def enqueue(
        self, *, marius_id, task_id, source, reason=None, continuation_attempt=0
    ) -> UUID:
        self.calls.append({"marius_id": marius_id, "task_id": task_id, "source": source})
        return uuid4()

    def woke(self, marius_id: UUID) -> bool:
        return any(c["marius_id"] == marius_id for c in self.calls)


class _FailingWake:
    """A wake backend that is down — every enqueue raises."""

    async def enqueue(self, **_kwargs) -> UUID:
        raise RuntimeError("wake backend unavailable")


async def _seed(leader_liveness: Liveness):
    factory = FakeUowFactory()
    ws = Workspace(name="Studio", slug="studio", owner_user_id="u1")
    factory.store.workspaces[ws.id] = ws
    projects = ProjectService(factory)
    project = await projects.create_project(
        ws.id,
        "Apollo",
        roles=[
            RoleSpec(key="leader", title="Leader", seats=1, is_leader=True),
            RoleSpec(key="backend", title="Backend", seats=1),
        ],
    )
    leader = Marius(workspace_id=ws.id, name="Lead", role="Leader", liveness=leader_liveness)
    worker = Marius(workspace_id=ws.id, name="Dev", role="Backend", liveness=Liveness.ONLINE)
    factory.store.mariuses[leader.id] = leader
    factory.store.mariuses[worker.id] = worker
    await projects.grant_seat(project.id, "leader", leader.id, system=True)
    await projects.grant_seat(project.id, "backend", worker.id, system=True)

    wake = _RecordingWake()
    commission = CommissionService(factory, wake)  # type: ignore[arg-type]
    return factory, commission, wake, project.id, leader.id, worker.id


async def test_commission_creates_draft_and_wakes_leader() -> None:
    factory, commission, wake, pid, leader_id, _worker = await _seed(Liveness.ONLINE)

    session = await commission.commission(project_id=pid, message="Build /login")

    assert session.status == CommissionStatus.OPEN
    assert session.leader_state == LeaderState.THINKING
    # A draft task was created…
    draft = factory.store.tasks[session.task_id]
    assert draft.status == TaskStatus.DRAFT
    # …and the Leader was woken to shape it (source=commission).
    assert wake.calls and wake.calls[-1]["marius_id"] == leader_id
    assert wake.calls[-1]["source"] == WakeSource.COMMISSION


async def test_commission_with_offline_leader_queues_no_wake() -> None:
    factory, commission, wake, pid, _leader, _worker = await _seed(Liveness.OFFLINE)

    session = await commission.commission(project_id=pid, message="Build /login")

    assert session.leader_state == LeaderState.LEADER_OFFLINE
    assert wake.calls == []  # queued, not run
    assert factory.store.tasks[session.task_id].status == TaskStatus.DRAFT


async def test_offline_commission_drains_when_leader_comes_online() -> None:
    factory, commission, wake, pid, leader_id, _worker = await _seed(Liveness.OFFLINE)
    session = await commission.commission(project_id=pid, message="Build /login")
    assert wake.calls == []

    drained = await commission.on_leader_online(leader_id)

    assert drained == 1
    assert wake.woke(leader_id)  # the queued turn was re-enqueued
    refreshed = await commission.get(session.id)
    assert refreshed.leader_state == LeaderState.THINKING


async def test_drain_leaves_session_queued_when_wake_fails() -> None:
    # A failed wake must NOT strand the turn as THINKING-but-never-woken — it stays queued
    # so the next drain retries it (no silently lost commission turn).
    factory, commission, _wake, pid, leader_id, _worker = await _seed(Liveness.OFFLINE)
    session = await commission.commission(project_id=pid, message="Build /login")
    assert session.leader_state == LeaderState.LEADER_OFFLINE

    failing = CommissionService(factory, _FailingWake())  # type: ignore[arg-type]
    drained = await failing.on_leader_online(leader_id)

    assert drained == 0
    refreshed = await failing.get(session.id)
    assert refreshed.leader_state == LeaderState.LEADER_OFFLINE  # still queued → retryable


async def test_confirm_flips_draft_to_todo_and_wakes_workers() -> None:
    factory, commission, wake, pid, leader_id, worker_id = await _seed(Liveness.ONLINE)
    session = await commission.commission(project_id=pid, message="Build /login")
    wake.calls.clear()  # ignore the leader-shaping wake

    confirmed = await commission.confirm(session.id)

    assert confirmed.status == CommissionStatus.CONFIRMED
    assert factory.store.tasks[session.task_id].status == TaskStatus.TODO
    # The seated worker (not the leader) is woken that a task hit the board.
    assert wake.woke(worker_id)
    assert not wake.woke(leader_id)


async def test_abandon_cancels_the_draft() -> None:
    factory, commission, _wake, pid, _leader, _worker = await _seed(Liveness.ONLINE)
    session = await commission.commission(project_id=pid, message="scrap this")

    abandoned = await commission.abandon(session.id)

    assert abandoned.status == CommissionStatus.ABANDONED
    assert factory.store.tasks[session.task_id].status == TaskStatus.CANCELLED


async def test_commission_without_seated_leader_is_rejected() -> None:
    factory = FakeUowFactory()
    ws = Workspace(name="Studio", slug="studio", owner_user_id="u1")
    factory.store.workspaces[ws.id] = ws
    projects = ProjectService(factory)
    project = await projects.create_project(
        ws.id,
        "Apollo",
        roles=[
            RoleSpec(key="leader", title="Leader", seats=1, is_leader=True),
            RoleSpec(key="backend", title="Backend", seats=1),
        ],
    )
    commission = CommissionService(factory, _RecordingWake())  # type: ignore[arg-type]

    with pytest.raises(CommissionError):
        await commission.commission(project_id=project.id, message="no leader yet")
