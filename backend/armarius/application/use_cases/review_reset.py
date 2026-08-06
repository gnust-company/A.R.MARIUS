"""Retiring a task's signatures when its deliverable goes back for rework (FR-033, FR-040).

One rule, one door. A signature stands for the deliverable that was on the table when it
was given; the moment the task goes back to being worked on, it stops standing for what is
in review. Nothing is deleted — the verdict, the reason and the signer stay exactly where
they were — the signature simply stops counting towards closing what replaces it.

This lives on its own because the *previous* version of this rule did not exist at all:
each caller worked out for itself which signatures were still current, and one of them
worked it out differently. A task pulled out of review by hand kept its Leader signature,
so the reworked version closed on a signature given for the draft before it — the exact
"fake done" the two-signature rule exists to prevent. Every route out of review now goes
through this function, and the function asks the domain, not the caller.
"""

from __future__ import annotations

from uuid import UUID

from armarius.application.ports.unit_of_work import UnitOfWork
from armarius.domain.entities.task import TaskStatus
from armarius.domain.services.approval_rules import signatures_cleared_by


async def retire_signatures_on_move(
    uow: UnitOfWork, task_id: UUID, target: TaskStatus
) -> int:
    """Retire this task's signatures if ``target`` means the work is being redone.

    Returns how many were retired — zero on the moves that keep them, and zero on a task
    that had none, which is most moves. Safe to call on every transition, and meant to be:
    a caller that has to decide *whether* to call it is a caller that can decide wrong.
    """
    if not signatures_cleared_by(target):
        return 0
    return await uow.approvals.supersede_for_task(task_id)
