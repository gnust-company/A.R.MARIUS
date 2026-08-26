"""Putting one real run on the shelf, for tests about what comes back off it.

The rows are written directly, but the *shelving* goes through `DaemonAdapter.dispatch` —
the only thing in the system that ever writes a shelf row. A hand-written claim row would
let a test pass against a shape nothing produces.

A run needs a task and a task needs a project, and neither is decoration: the message handed
over with the work is built out of both (FR-011), so a run floating free of them is a run
the door has nothing to say about.
"""

from __future__ import annotations

from uuid import UUID, uuid4

from armarius.application.ports.adapter import ExecContext
from armarius.domain.entities.project import ProjectStatus
from armarius.domain.entities.run import RunStatus
from armarius.domain.entities.task import TaskStatus
from armarius.infrastructure.database.engine import get_sessionmaker
from armarius.infrastructure.database.models import (
    ProjectModel,
    RunModel,
    TaskModel,
)
from armarius.main import app
from armarius.shared.clock import utcnow


async def a_project(workspace_id: str | UUID, *, name: str = "Apollo") -> UUID:
    project_id = uuid4()
    async with get_sessionmaker()() as session:
        session.add(
            ProjectModel(
                id=project_id,
                workspace_id=UUID(str(workspace_id)),
                name=name,
                slug=f"{name.lower()}-{project_id.hex[:6]}",
                key=project_id.hex[:6].upper(),
                status=ProjectStatus.OPERATING.value,
                created_at=utcnow(),
            )
        )
        await session.commit()
    return project_id


async def a_task(
    project_id: UUID,
    *,
    assigned_to: str | UUID | None = None,
    title: str = "Ship the thing",
    description: str = "Whatever the patron asked for.",
    next_action: str | None = None,
) -> UUID:
    task_id = uuid4()
    async with get_sessionmaker()() as session:
        session.add(
            TaskModel(
                id=task_id,
                project_id=project_id,
                title=title,
                description=description,
                status=TaskStatus.TODO.value,
                next_action=next_action,
                assigned_marius_id=UUID(str(assigned_to)) if assigned_to else None,
                created_at=utcnow(),
            )
        )
        await session.commit()
    return task_id


async def shelve(*, marius_id: str | UUID, task_id: UUID) -> UUID:
    """One run, queued and waiting at the place its agent was put in (FR-053)."""
    run_id = uuid4()
    async with get_sessionmaker()() as session:
        session.add(
            RunModel(
                id=run_id,
                marius_id=UUID(str(marius_id)),
                task_id=task_id,
                adapter_type="daemon",
                status=RunStatus.QUEUED.value,
                created_at=utcnow(),
            )
        )
        await session.commit()
    adapter = app.state.container.registry.get("daemon")
    await adapter.dispatch(
        ExecContext(
            prompt="",
            adapter_config={},
            marius_id=UUID(str(marius_id)),
            task_id=task_id,
            run_id=run_id,
        )
    )
    return run_id
