"""WakeupRequest entity — a queued, task-scoped request to wake a Marius (§4.3).

Every wake is task-scoped (it routes into that task's session). There is no global
exploratory timer; wakes come from events or from the self/liveness policy.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from uuid import UUID, uuid4

from armarius.domain.entities.run import WakeSource


class WakeupStatus(StrEnum):
    QUEUED = "queued"
    DISPATCHED = "dispatched"
    COALESCED = "coalesced"  # folded into an already-running wake for same (marius, task)
    DONE = "done"
    FAILED = "failed"
    # Two ways a pending wake can end without ever being delivered. They look the same in
    # a table and mean opposite things, so they get their own names: reading `failed` for
    # both would make the audit trail unable to answer "did we drop this, or did something
    # replace it?".
    SUPERSEDED = "superseded"  # a newer pending wake for the same pair took its place
    ORPHANED = "orphaned"  # no run was ever going to close it (the process that owned it died)


# The two statuses that mean "this wake is still owed". FR-050 allows at most one of these
# per (agent, task) at a time, and the storage layer enforces it — a partial unique index
# rather than a check in application code, so a second process or a restart cannot slip a
# duplicate past it.
PENDING_WAKEUP_STATUSES: frozenset[WakeupStatus] = frozenset(
    {WakeupStatus.QUEUED, WakeupStatus.DISPATCHED}
)


class WakePairBusyError(Exception):
    """The storage layer refused a second pending wake for one (agent, task) pair.

    Raised by the repository when the unique index trips, i.e. when two causes raced each
    other. The caller's answer is never to force the write through — it is to re-read and
    fold the losing cause into the wake that won.
    """


@dataclass
class WakeupRequest:
    id: UUID = field(default_factory=uuid4)
    project_id: UUID | None = None
    marius_id: UUID | None = None
    task_id: UUID | None = None
    source: WakeSource = WakeSource.ON_DEMAND
    reason: str | None = None
    prompt: str | None = None  # optional pre-built wake prompt
    status: WakeupStatus = WakeupStatus.QUEUED
    run_id: UUID | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
