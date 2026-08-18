"""Pure project rules (LLD §3.1, §4; spec 001 FR-001 → FR-006) — no I/O.

Three decisions the application layer leans on:
  - `validate_plan` — the hard roster rule at create time: exactly one leader role with
    `seats == 1`, plus at least one non-leader role with `seats >= 1`.
  - `recompute_active` — a project flips `setup → planning` ONCE, when every role seat is
    granted AND every seated agent is ONLINE; it never rolls back. Note the destination:
    a full roster buys you the right to *plan*, not the right to start working.
  - the phase table — which phase may follow which, plus the two gates keyed off phase:
    `accepts_real_tasks` (FR-003) and `is_closed` (FR-005).
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Mapping
from uuid import UUID

from armarius.domain.entities.marius import Liveness
from armarius.domain.entities.project import Project, ProjectStatus
from armarius.domain.entities.role import Role
from armarius.domain.entities.seat_grant import SeatGrant
from armarius.shared.errors import CodedError


class InvalidProjectPlan(CodedError):
    """Raised when a roster plan violates the leader/worker rule (LLD §4)."""


class ProjectClosed(CodedError):
    """Raised when anything tries to write to a closed project (FR-005).

    Lives here, beside `is_closed`, because "closed means frozen" is one rule with one
    meaning. It used to be three identical classes in three services, which is how a rule
    ends up enforced in three places and skipped in thirty.
    """


class InvalidPhaseTransition(CodedError):
    """Raised when a phase change is not on the map (spec 001 FR-004, FR-005)."""


# The whole lifecycle, in one place. Everything not listed here is refused, including a
# phase transitioning to itself — "no change" is not a decision worth recording.
PHASE_TRANSITIONS: dict[ProjectStatus, frozenset[ProjectStatus]] = {
    # A full, online roster opens the planning gate — never work directly.
    ProjectStatus.SETUP: frozenset({ProjectStatus.PLANNING}),
    # Only the patron's approval at the plan gate gets you out of here.
    ProjectStatus.PLANNING: frozenset({ProjectStatus.OPERATING}),
    ProjectStatus.OPERATING: frozenset({ProjectStatus.MAINTAINING, ProjectStatus.CLOSED}),
    ProjectStatus.MAINTAINING: frozenset({ProjectStatus.OPERATING, ProjectStatus.CLOSED}),
    # Terminal. Reopening is a new project, not a resurrection (FR-005).
    ProjectStatus.CLOSED: frozenset(),
}

# Phases in which a real (non-draft) task may be created or assigned (FR-003).
TASK_ACCEPTING_PHASES: frozenset[ProjectStatus] = frozenset(
    {ProjectStatus.OPERATING, ProjectStatus.MAINTAINING}
)


def can_change_phase(current: ProjectStatus, target: ProjectStatus) -> bool:
    """True when `current → target` is on the map."""
    return target in PHASE_TRANSITIONS.get(current, frozenset())


def assert_phase_transition(current: ProjectStatus, target: ProjectStatus) -> None:
    """Raise `InvalidPhaseTransition` unless `current → target` is allowed."""
    if not can_change_phase(current, target):
        raise InvalidPhaseTransition(
            "project_phase_transition_invalid", current=current, target=target
        )


def accepts_real_tasks(phase: ProjectStatus) -> bool:
    """FR-003 — a real task exists only once the plan has been approved."""
    return phase in TASK_ACCEPTING_PHASES


def is_closed(phase: ProjectStatus) -> bool:
    """FR-005 — a closed project is history: readable, never writable."""
    return phase is ProjectStatus.CLOSED


def validate_plan(roles: Iterable[Role]) -> None:
    """Enforce the create-time roster rule (LLD §2.3, §4; spec 03 §1.1, §3.1).

    Exactly one leader role, the leader has `seats == 1`, there is at least one non-leader
    role with `seats >= 1`, AND **every** role carries a non-empty description (so the wake /
    leader-chat prompts can tell each agent what its role — and its teammates' roles — do).

    Composition is checked first so a plan that is invalid for a stronger reason (no leader,
    wrong seat count) fails on that, not on a missing description.
    """
    roles = list(roles)
    leaders = [r for r in roles if r.is_leader]
    if len(leaders) != 1:
        raise InvalidProjectPlan("project_needs_one_leader_role", found=len(leaders))
    if leaders[0].seats != 1:
        raise InvalidProjectPlan("leader_role_needs_one_seat")
    workers = [r for r in roles if not r.is_leader and r.seats >= 1]
    if not workers:
        raise InvalidProjectPlan("project_needs_a_worker_role")
    undescribed = [r for r in roles if not (r.description or "").strip()]
    if undescribed:
        titles = ", ".join(r.title or r.key for r in undescribed)
        raise InvalidProjectPlan("role_needs_a_description", roles=titles)
    # One key per project. `add_role` refuses a colliding key one role at a time, but a
    # whole roster arriving at once never passed through that check — and the onboarding
    # door hands the agent's own drafted keys straight in, so two roles both titled
    # "Backend" became two rows sharing a key. Everything that addresses a role by key
    # then answers from whichever row the database returned first, which is no answer.
    counted = Counter(r.key for r in roles)
    repeated = sorted(key for key, n in counted.items() if n > 1)
    if repeated:
        raise InvalidProjectPlan("role_keys_must_be_unique", keys=", ".join(repeated))


def seats_filled(roles: Iterable[Role], grants: Iterable[SeatGrant]) -> bool:
    """True when every role has at least `seats` agents in it.

    Counted by role **identity**: the seat points at the role row, so renaming a role does
    not empty it.
    """
    filled = Counter(g.role_id for g in grants)
    return all(filled.get(r.id, 0) >= r.seats for r in roles)


def all_seated_online(
    grants: Iterable[SeatGrant],
    liveness_by_marius: Mapping[UUID, Liveness],
) -> bool:
    """True when there is at least one seat and every seated agent is ONLINE."""
    seated = list(grants)
    if not seated:
        return False
    return all(liveness_by_marius.get(g.marius_id) == Liveness.ONLINE for g in seated)


def should_activate(
    roles: Iterable[Role],
    grants: Iterable[SeatGrant],
    liveness_by_marius: Mapping[UUID, Liveness],
) -> bool:
    """The activation predicate: all seats granted AND all seated agents ONLINE."""
    roles = list(roles)
    grants = list(grants)
    return seats_filled(roles, grants) and all_seated_online(grants, liveness_by_marius)


def recompute_active(
    project: Project,
    roles: Iterable[Role],
    grants: Iterable[SeatGrant],
    liveness_by_marius: Mapping[UUID, Liveness],
) -> bool:
    """Flip `setup → planning` once the predicate holds. True iff it just moved.

    Idempotent and one-way: a project already past setup is left untouched, and an agent
    going offline later does NOT drag it back (spec 001 FR-002). The predicate is
    unchanged from the original rule — only the destination moved, because a full roster
    now means "we can start planning", not "we can start working".
    """
    if project.status != ProjectStatus.SETUP:
        return False
    if should_activate(roles, grants, liveness_by_marius):
        project.status = ProjectStatus.PLANNING
        return True
    return False
