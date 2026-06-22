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
