"""Task use cases — create, list, assign (→ event-wake), and gated status transitions."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from uuid import UUID

from armarius.application.ports.unit_of_work import UnitOfWork
from armarius.application.use_cases.types import UowFactory
from armarius.application.use_cases.wake_engine import WakeEngine
from armarius.domain.entities.run import WakeSource
from armarius.domain.entities.task import (
    DEPENDENCY_GATED_STATUSES,
    Task,
    TaskPriority,
    TaskStatus,
)
from armarius.domain.entities.task_dependency import TaskDependency, TaskDependencyError
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
            project = await uow.projects.get(project_id)
            if project is None:
                raise LookupError("project not found")
            # Mint "{KEY}-{seq}" — the seq is allocated atomically (UPDATE … RETURNING) so
            # concurrent creates never share a number and the number is never reused.
            seq = await uow.projects.allocate_task_number(project_id)
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
                identifier=f"{project.key}-{seq}",
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
            deps_satisfied = await uow.dependencies.all_blockers_done(task_id)
            # DRAFT → TODO (raises on illegal transition or an unfinished blocked_by).
            task.transition_to(TaskStatus.TODO, now, deps_satisfied=deps_satisfied)
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
            # Convenience promotion backlog→todo, but honour the dependency-gate: a task
            # with an unfinished blocked_by stays in backlog rather than being forced up.
            if task.status == TaskStatus.BACKLOG and await uow.dependencies.all_blockers_done(
                task_id
            ):
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
                deps_satisfied = await uow.dependencies.all_blockers_done(task_id)
                task.transition_to(
                    TaskStatus.IN_PROGRESS, utcnow(), deps_satisfied=deps_satisfied
                )
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
        """Apply a gated status transition — enforces the DONE-gate (artifact, §3.4)
        and the dependency-gate (§1.3): entering todo/in_progress while a `blocked_by`
        task is unfinished raises ``DependencyNotMetError``."""
        async with self._uow() as uow:
            task = await uow.tasks.get(task_id)
            if task is None:
                raise LookupError("task not found")
            artifact_count = await uow.artifacts.count_by_task(task_id)
            deps_satisfied = True
            if target in DEPENDENCY_GATED_STATUSES:
                deps_satisfied = await uow.dependencies.all_blockers_done(task_id)
            task.transition_to(
                target,
                utcnow(),
                has_artifact=artifact_count > 0,
                deps_satisfied=deps_satisfied,
                reason=reason,
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

    # ── Dependency edges (feed the dependency-gate, §1.3) ──────────────────────
    async def add_dependency(
        self, task_id: UUID, blocks_task_id: UUID
    ) -> TaskDependency:
        """Add a `blocked_by` edge: ``task_id`` waits on ``blocks_task_id``. Both tasks
        must exist in the same project. Rejects self-loops, duplicate pairs, and edges
        that would close a dependency cycle (all → ``TaskDependencyError`` → 422)."""
        async with self._uow() as uow:
            task = await uow.tasks.get(task_id)
            blocker = await uow.tasks.get(blocks_task_id)
            if task is None or blocker is None:
                raise LookupError("task not found")
            if task.project_id != blocker.project_id:
                raise TaskDependencyError("A dependency must stay within one project.")
            # Construct first: the entity rejects a self-loop in __post_init__.
            edge = TaskDependency(task_id=task_id, blocks_task_id=blocks_task_id)
            if await uow.dependencies.get(task_id, blocks_task_id) is not None:
                raise TaskDependencyError("This dependency already exists.")
            if await self._would_cycle(uow, task_id, blocks_task_id):
                raise TaskDependencyError("This dependency would create a cycle.")
            created = await uow.dependencies.add(edge)
            await uow.commit()
            return created

    async def remove_dependency(self, task_id: UUID, blocks_task_id: UUID) -> None:
        """Remove a `blocked_by` edge (idempotent — a missing edge is a no-op)."""
        async with self._uow() as uow:
            await uow.dependencies.remove(task_id, blocks_task_id)
            await uow.commit()

    async def list_blockers(self, task_id: UUID) -> list[Task]:
        """The tasks ``task_id`` is blocked_by, as full tasks (for rendering)."""
        async with self._uow() as uow:
            blockers: list[Task] = []
            for edge in await uow.dependencies.list_blockers(task_id):
                if edge.blocks_task_id is None:
                    continue
                bt = await uow.tasks.get(edge.blocks_task_id)
                if bt is not None:
                    blockers.append(bt)
            return blockers

    async def list_project_dependencies(
        self, project_id: UUID
    ) -> Sequence[TaskDependency]:
        """All `blocked_by` edges in a project — the board reads these to flag which
        cards are blocked (a blocker not yet done)."""
        async with self._uow() as uow:
            return await uow.dependencies.list_by_project(project_id)

    async def _would_cycle(
        self, uow: UnitOfWork, task_id: UUID, blocks_task_id: UUID
    ) -> bool:
        """Would adding "task_id blocked_by blocks_task_id" close a cycle? True when
        ``task_id`` is already reachable from ``blocks_task_id`` via existing edges."""
        seen: set[UUID] = set()
        frontier: list[UUID] = [blocks_task_id]
        while frontier:
            current = frontier.pop()
            if current == task_id:
                return True
            if current in seen:
                continue
            seen.add(current)
            for edge in await uow.dependencies.list_blockers(current):
                if edge.blocks_task_id is not None:
                    frontier.append(edge.blocks_task_id)
        return False
