"""Run & RunEvent entities — one bounded execution and its traced event stream (§8.1)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from uuid import UUID, uuid4


class RunStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    TIMED_OUT = "timed_out"
    STOPPED = "stopped"


class WakeSource(StrEnum):
    """Why a run was started (§4.3 wake families)."""

    ASSIGNMENT = "assignment"
    MENTION = "mention"
    COMMENT = "comment"
    ON_DEMAND = "on_demand"
    CONTINUATION = "continuation"  # self/liveness-wake resuming a dropped run
    NUDGE = "nudge"
    LEADER_CHAT = "leader_chat"  # a Leader turn in the project-level Chat-with-Leader tab (#82)
    # Project-level wakes (spec 001). Neither is task-scoped: they are about the project
    # as a whole, so they ride the shared project session rather than a task session.
    PROJECT_READY = "project_ready"  # roster complete + everyone online → go plan (FR-002)
    PATRON_DECISION = "patron_decision"  # the patron decided something (FR-013, FR-004)
    TASK_DONE = "task_done"  # a task reached *done* → go pass the word (FR-031)
    WORKER_HANDBACK = "worker_handback"  # a worker handed work back or asked (FR-071)
    # Story 3 wakes: an output was sent back for rework (FR-040), and the brake that pulls
    # the Leader back to the brief after three rounds (FR-041).
    APPROVAL_REJECTED = "approval_rejected"
    BRIEF_REVIEW = "brief_review"


@dataclass
class Run:
    id: UUID = field(default_factory=uuid4)
    project_id: UUID | None = None
    marius_id: UUID | None = None
    task_id: UUID | None = None
    adapter_type: str = ""
    wake_source: WakeSource = WakeSource.ON_DEMAND
    trigger_detail: str | None = None
    status: RunStatus = RunStatus.QUEUED
    external_run_id: str | None = None
    session_id_before: str | None = None
    session_id_after: str | None = None
    usage_json: dict = field(default_factory=dict)
    error: str | None = None
    next_action: str | None = None
    continuation_attempt: int = 0
    started_at: datetime | None = None
    finished_at: datetime | None = None
    last_output_at: datetime | None = None
    created_at: datetime | None = None


@dataclass
class RunEvent:
    """A single traced event teed from the adapter stream (e.g. Hermes SSE)."""

    id: UUID = field(default_factory=uuid4)
    run_id: UUID | None = None
    seq: int = 0
    type: str = ""  # run.started | assistant.delta | tool.started | ...
    payload: dict = field(default_factory=dict)
    created_at: datetime | None = None
