"""The question a machine asks before it deletes anything of its own (FR-021, FR-021a).

The direction is the whole point. The server never tells a machine *this task is finished, let
its directory go*: a message like that can be sent while the machine is switched off, and a
machine that missed it would hold the directory forever. So the machine asks, on its own
schedule, about the directories it actually has — a question asked late is still answered, and
that is the failure mode worth having (chốt 2026-08-22, following Multica).

Two answers, and the difference between them decides how long a directory survives:

  * a task that comes back **named** was found in this machine's workspace, and what it says
    about itself — closed or not, and how long since anything happened — is what FR-021 acts on.
  * a task that comes back **missing** is one the server cannot account for at all: deleted,
    never recorded, or belonging to somebody else. That is the weaker evidence of the two, and
    the sweep gives it the much longer clock of FR-021a.

Because *missing* covers "belongs to somebody else", this door needs no refusal branch to
satisfy Constitution I. A task next door and a task that never existed are the same silence.

Infrastructure only (Constitution III): nothing above learns that a machine keeps directories.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from armarius.domain.entities.task import TaskStatus
from armarius.infrastructure.daemon.enrollment import MachineIdentity
from armarius.infrastructure.database.engine import get_sessionmaker
from armarius.infrastructure.database.models import ProjectModel, TaskModel
from armarius.shared.clock import as_utc, utcnow

#: How many tasks one ask may carry. A machine with more directories than this asks more than
#: once — the ceiling is here to bound a single request, not to bound a sweep.
MAX_TASKS_PER_ASK = 200

#: What counts as closed, and nothing else does (FR-021). A blocked task is not closed, an
#: abandoned one is not closed: both can still be picked up, and their directory is still the
#: place that would be picked up from.
_CLOSED = frozenset({TaskStatus.DONE, TaskStatus.CANCELLED})


@dataclass(frozen=True)
class TaskState:
    """One task as the sweep needs to see it."""

    task_id: UUID
    closed: bool
    #: When anything last happened to this task. Read from the task's own row rather than
    #: assembled from its runs: every edit and every transition moves it, and a run ending is
    #: one of the things that moves it. A join over the run log would buy seconds of accuracy
    #: against a retention measured in days.
    last_activity: datetime


class DaemonHousekeepingService:
    """Answers the sweep. Reads two tables and writes nothing."""

    def __init__(self, sessionmaker: async_sessionmaker[AsyncSession] | None = None) -> None:
        self._sessionmaker = sessionmaker

    def _sessions(self) -> async_sessionmaker[AsyncSession]:
        # Resolved on use, like the other daemon services: the container is built before the
        # engine is necessarily pointed at its database.
        return self._sessionmaker or get_sessionmaker()

    async def task_states(
        self, machine: MachineIdentity, task_ids: Sequence[str]
    ) -> list[TaskState]:
        """Say what this machine's workspace knows about each of these tasks.

        Names that are not task ids at all are dropped rather than refused. The machine reads
        them off its own disk, where a directory can be named anything a person or a crash left
        behind, and answering 422 to the whole ask would stop the sweep over one stray name.
        Dropped is also the *right* answer for such a name: nothing will ever claim that
        directory, which is exactly the case FR-021a was written for.
        """
        wanted = _as_ids(task_ids)
        if not wanted:
            return []

        async with self._sessions()() as session:
            rows = (
                await session.execute(
                    select(
                        TaskModel.id,
                        TaskModel.status,
                        TaskModel.updated_at,
                        TaskModel.completed_at,
                        TaskModel.created_at,
                    )
                    .join(ProjectModel, ProjectModel.id == TaskModel.project_id)
                    .where(
                        TaskModel.id.in_(wanted),
                        ProjectModel.workspace_id == machine.workspace_id,
                    )
                )
            ).all()

        now = utcnow()
        return [
            TaskState(
                task_id=row.id,
                closed=row.status in _CLOSED,
                last_activity=_latest(
                    (row.updated_at, row.completed_at, row.created_at), fallback=now
                ),
            )
            for row in rows
        ]


def _as_ids(names: Sequence[str]) -> list[UUID]:
    ids: list[UUID] = []
    for name in names:
        try:
            ids.append(UUID(name))
        except ValueError:
            continue
    return ids


def _latest(stamps: Sequence[datetime | None], *, fallback: datetime) -> datetime:
    """The most recent of whatever was filled in, and *now* when nothing was.

    The fallback errs towards keeping. A task with no timestamp anywhere is a row that should
    not exist, and the two ways to be wrong about it are not equal: calling it ancient hands a
    directory to `RemoveAll`, calling it fresh costs one more sweep.
    """
    known = [aware for s in stamps if (aware := as_utc(s)) is not None]
    return max(known) if known else fallback
