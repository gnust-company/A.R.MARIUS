"""A task on its way out, carrying the signatures it actually holds (FR-033a).

`TaskOut.signatures` was declared the day the board was drawn and filled by nothing: the
two-signature rule was built later, wrote its rows to their own table, and nobody came back
for the field. So every reader of a task — the board, the room, and a Leader asked where
the project stands — was handed an empty list on a task both sides had signed. A Leader
reading its own board reported exactly that to the patron: *done, and signed by nobody*
(measured 2026-11-13).

One funnel rather than a line at each door, for the reason the stall verdict is split
inside the schema: there are some twenty places a task leaves through, and a field one of
them forgets is a field that is true on one screen and false on the next.

Only the signatures that speak for the deliverable now in review (`current_signatures`).
The ones retired when the work went back are history and stay behind the door that lists
history, `GET /v1/tasks/{id}/approvals`.
"""

from __future__ import annotations

from collections.abc import Sequence

from armarius.domain.entities.task import Task
from armarius.presentation.container import Container
from armarius.presentation.schemas import SignatureOut, TaskOut


async def tasks_out(container: Container, tasks: Sequence[Task]) -> list[TaskOut]:
    """Many tasks, one read of their signatures — a board is not a round trip per card."""
    signed = await container.approvals.current_for_tasks([task.id for task in tasks])
    rows: list[TaskOut] = []
    for task in tasks:
        row = TaskOut.model_validate(task)
        row.signatures = [
            SignatureOut.model_validate(one) for one in signed.get(task.id, ())
        ]
        rows.append(row)
    return rows


async def task_out(container: Container, task: Task) -> TaskOut:
    """One task as it leaves the server."""
    return (await tasks_out(container, [task]))[0]
