"""Task change log — append-only, per-task ordering (spec 001 §10, FR-079).

Drives the real `SqlAlchemyUnitOfWork` so the ordering guarantee is proven against the
database, not against an in-memory list. The log is the evidence trail FR-021, FR-039,
FR-061 and FR-079 all read from, so its two invariants are non-negotiable:

  1. entries are only appended — nothing edits or deletes an existing line;
  2. `seq` is per-task, monotonic and gap-free, so the timeline is stable even when two
     entries land in the same clock tick.
"""

from __future__ import annotations

from uuid import UUID, uuid4

from armarius.application.use_cases.task_log import TaskLogService
from armarius.domain.entities.project import Project
from armarius.domain.entities.task import Task
from armarius.domain.entities.task_log import ActorKind, TaskLogKind
from armarius.domain.entities.workspace import Workspace


async def _real_task(uow_factory, *, title: str = "Việc") -> UUID:
    """A committed task row to hang the log off.

    The log carries a real foreign key to `tasks`, and the test database enforces foreign
    keys the same way the deployed one does — so a made-up task id is not a shortcut, it
    is a row the database will refuse.
    """
    async with uow_factory() as uow:
        workspace = await uow.workspaces.add(Workspace(name="WS", slug="ws"))
        project = await uow.projects.add(
            Project(workspace_id=workspace.id, name="P", slug="p", key="P")
        )
        task = await uow.tasks.add(Task(project_id=project.id, title=title))
        await uow.commit()
        return task.id


async def test_appends_in_order_with_per_task_seq(uow_factory) -> None:
    log = TaskLogService(uow_factory)
    task_id = await _real_task(uow_factory)

    await log.record(
        task_id,
        TaskLogKind.STATUS_CHANGED,
        actor_kind=ActorKind.SYSTEM,
        before="todo",
        after="in_progress",
    )
    await log.record(
        task_id,
        TaskLogKind.ASSIGNED,
        actor_kind=ActorKind.USER,
        actor_user_id="u1",
        after="marius-a",
    )
    await log.record(
        task_id,
        TaskLogKind.STATUS_CHANGED,
        actor_kind=ActorKind.AGENT,
        before="in_progress",
        after="in_review",
        reason="nộp bài",
    )

    entries = await log.list_for_task(task_id)
    assert [e.seq for e in entries] == [1, 2, 3]
    assert [e.kind for e in entries] == [
        TaskLogKind.STATUS_CHANGED,
        TaskLogKind.ASSIGNED,
        TaskLogKind.STATUS_CHANGED,
    ]
    assert entries[2].reason == "nộp bài"
    assert entries[0].created_at is not None


async def test_seq_is_scoped_per_task(uow_factory) -> None:
    """Two tasks each start their own numbering — one task's history never renumbers
    because another task was busy."""
    log = TaskLogService(uow_factory)
    task_a = await _real_task(uow_factory, title="Một")
    task_b = await _real_task(uow_factory, title="Hai")

    await log.record(task_a, TaskLogKind.STATUS_CHANGED, after="todo")
    await log.record(task_b, TaskLogKind.STATUS_CHANGED, after="todo")
    await log.record(task_a, TaskLogKind.STATUS_CHANGED, before="todo", after="in_progress")

    assert [e.seq for e in await log.list_for_task(task_a)] == [1, 2]
    assert [e.seq for e in await log.list_for_task(task_b)] == [1]


async def test_log_is_append_only(uow_factory) -> None:
    """There is no update and no delete on the port — recording a correction appends a
    new line instead of rewriting history."""
    log = TaskLogService(uow_factory)
    task_id = await _real_task(uow_factory)
    await log.record(task_id, TaskLogKind.STATUS_CHANGED, after="in_progress")

    async with uow_factory() as uow:
        repo = uow.task_logs
        assert not hasattr(repo, "update")
        assert not hasattr(repo, "remove")
        assert not hasattr(repo, "delete")

    await log.record(task_id, TaskLogKind.STATUS_CHANGED, before="in_progress", after="todo")
    entries = await log.list_for_task(task_id)
    assert len(entries) == 2
    assert entries[0].after == "in_progress"


async def test_records_actor_and_structured_detail(uow_factory) -> None:
    log = TaskLogService(uow_factory)
    task_id = await _real_task(uow_factory)
    marius_id = uuid4()

    await log.record(
        task_id,
        TaskLogKind.ESCALATED,
        actor_kind=ActorKind.SYSTEM,
        actor_marius_id=marius_id,
        detail={"level": 3, "tried": ["re-wake", "reassign"]},
    )

    entry = (await log.list_for_task(task_id))[0]
    assert entry.actor_kind is ActorKind.SYSTEM
    assert entry.actor_marius_id == marius_id
    assert entry.detail == {"level": 3, "tried": ["re-wake", "reassign"]}
