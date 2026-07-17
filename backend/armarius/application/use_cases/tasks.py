"""Task use cases — create, list, assign (→ event-wake), and gated status transitions."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from uuid import UUID

from armarius.application.use_cases.types import UowFactory
from armarius.application.use_cases.wake_engine import WakeEngine
from armarius.domain.entities.run import WakeSource
from armarius.domain.entities.task import Task, TaskPriority, TaskStatus
from armarius.shared.clock import utcnow


def _coerce_priority(value: str | TaskPriority | None) -> TaskPriority:
    """Map a patron/agent-supplied priority to the enum; unknown/empty → MEDIUM."""
    if value is None or value == "":
        return TaskPriority.MEDIUM
    try:
        return TaskPriority(str(value).lower())
    except ValueError:
        return TaskPriority.MEDIUM


class TaskService:
    def __init__(self, uow_factory: UowFactory, wake_engine: WakeEngine) -> None:
        self._uow = uow_factory
        self._wake = wake_engine

    async def create(
        self,
        *,
        project_id: UUID,
        title: str,
        description: str | None = None,
        status: TaskStatus = TaskStatus.BACKLOG,
        priority: str | TaskPriority | None = None,
        due_date: datetime | None = None,
        definition_of_done: str | None = None,
        created_by_user_id: str | None = None,
        created_by_marius_id: UUID | None = None,
        assigned_marius_id: UUID | None = None,
    ) -> Task:
        """Create a task. Defaults to a ``backlog`` task; the Leader's Chat-with-Leader
        proposals pass ``status=DRAFT`` + a proposed ``assigned_marius_id`` so the task
        waits for the patron's approval before any worker is woken (#82). The patron's manual
        add-task supplies the full definition — priority/due_date/definition_of_done/assignee."""
        async with self._uow() as uow:
            if await uow.projects.get(project_id) is None:
                raise LookupError("project not found")
            now = utcnow()
            task = Task(
                project_id=project_id,
                title=title,
                description=description,
                status=status,
                priority=_coerce_priority(priority),
                due_date=due_date,
                definition_of_done=definition_of_done,
                created_by_user_id=created_by_user_id,
                created_by_marius_id=created_by_marius_id,
                assigned_marius_id=assigned_marius_id,
                created_at=now,
                updated_at=now,
            )
            created = await uow.tasks.add(task)
            await uow.commit()
            return created

    async def approve_proposed(self, task_id: UUID) -> Task:
        """Approve a Leader-proposed draft: ``draft → todo``, then wake the proposed
        assignee (if any). 409 if the task is not a draft (invalid transition)."""
        assignee: UUID | None = None
        async with self._uow() as uow:
            task = await uow.tasks.get(task_id)
            if task is None:
                raise LookupError("task not found")
            now = utcnow()
            task.transition_to(TaskStatus.TODO, now)  # DRAFT → TODO (raises otherwise)
            task.updated_at = now
            updated = await uow.tasks.update(task)
            await uow.commit()
            assignee = updated.assigned_marius_id

        if assignee is not None:
            await self._wake.enqueue(
                marius_id=assignee,
                task_id=task_id,
                source=WakeSource.ASSIGNMENT,
                reason="you were assigned to this task",
            )
        return updated

    async def reject_proposed(self, task_id: UUID) -> Task:
        """Reject a Leader-proposed draft: ``draft → cancelled`` (no wake)."""
        async with self._uow() as uow:
            task = await uow.tasks.get(task_id)
            if task is None:
                raise LookupError("task not found")
            now = utcnow()
            task.transition_to(TaskStatus.CANCELLED, now)  # DRAFT → CANCELLED
            task.updated_at = now
            updated = await uow.tasks.update(task)
            await uow.commit()
            return updated

    async def get(self, task_id: UUID) -> Task | None:
        async with self._uow() as uow:
            return await uow.tasks.get(task_id)

    async def get_in_workspace(self, task_id: UUID, workspace_id: UUID) -> Task:
        """The task, only if it lives in this workspace (agent ws-consistency, #15).

        Agent tokens are per-workspace; a cross-workspace task_id reads as "not
        found" so a token can't act on — or probe for — another workspace's tasks.
        """
        async with self._uow() as uow:
            task = await uow.tasks.get(task_id)
            if task is None:
                raise LookupError("task not found")
            project = await uow.projects.get(task.project_id)
            if project is None or project.workspace_id != workspace_id:
                raise LookupError("task not found")
            return task

    async def list_by_project(
        self, project_id: UUID, *, statuses: list[str] | None = None
    ) -> Sequence[Task]:
        async with self._uow() as uow:
            return await uow.tasks.list_by_project(project_id, statuses=statuses)

    async def assign(self, task_id: UUID, marius_id: UUID) -> Task:
        """Assign a Marius and fire an assignment event-wake (§4.3 family 1)."""
        async with self._uow() as uow:
            task = await uow.tasks.get(task_id)
            if task is None:
                raise LookupError("task not found")
            if await uow.mariuses.get(marius_id) is None:
                raise LookupError("marius not found")
            task.assigned_marius_id = marius_id
            if task.status == TaskStatus.BACKLOG:
                task.status = TaskStatus.TODO
            task.updated_at = utcnow()
            await uow.tasks.update(task)
            await uow.commit()

        await self._wake.enqueue(
            marius_id=marius_id,
            task_id=task_id,
            source=WakeSource.ASSIGNMENT,
            reason="you were assigned to this task",
        )
        return task

    async def claim(self, task_id: UUID, marius_id: UUID) -> Task:
        """Agent claims a task: assign self and start working. No wake is fired
        (the claiming agent is already awake)."""
        async with self._uow() as uow:
            task = await uow.tasks.get(task_id)
            if task is None:
                raise LookupError("task not found")
            task.assigned_marius_id = marius_id
            if task.status in (TaskStatus.BACKLOG, TaskStatus.TODO):
                task.transition_to(TaskStatus.IN_PROGRESS, utcnow())
            task.updated_at = utcnow()
            updated = await uow.tasks.update(task)
            await uow.commit()
            return updated

    async def transition(
        self,
        task_id: UUID,
        target: TaskStatus,
        *,
        reason: str | None = None,
    ) -> Task:
        """Apply a gated status transition (enforces the artifact rule, §3.4)."""
        async with self._uow() as uow:
            task = await uow.tasks.get(task_id)
            if task is None:
                raise LookupError("task not found")
            artifact_count = await uow.artifacts.count_by_task(task_id)
            task.transition_to(
                target, utcnow(), has_artifact=artifact_count > 0, reason=reason
            )
            task.updated_at = utcnow()
            updated = await uow.tasks.update(task)
            await uow.commit()
            return updated

    async def set_next_action(self, task_id: UUID, next_action: str | None) -> Task:
        async with self._uow() as uow:
            task = await uow.tasks.get(task_id)
            if task is None:
                raise LookupError("task not found")
            task.next_action = next_action
            task.updated_at = utcnow()
            updated = await uow.tasks.update(task)
            await uow.commit()
            return updated
