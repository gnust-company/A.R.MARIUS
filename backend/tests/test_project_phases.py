"""Five project phases, as pure rules (spec 001 FR-001 → FR-006).

Phases replace the old three-value lifecycle. Everything here is a function of values —
no database, no clock — so the law is testable on its own and the application layer only
has to obey it.
"""

from __future__ import annotations

from uuid import uuid4

import pytest

from armarius.domain.entities.marius import Liveness
from armarius.domain.entities.project import Project, ProjectStatus
from armarius.domain.entities.role import Role
from armarius.domain.entities.seat_grant import SeatGrant
from armarius.domain.services.project_rules import (
    InvalidPhaseTransition,
    accepts_real_tasks,
    assert_phase_transition,
    can_change_phase,
    is_closed,
    recompute_active,
)

_ids = [uuid4(), uuid4()]


def _roster() -> tuple[list[Role], list[SeatGrant], dict]:
    roles = [
        Role(key="leader", title="Leader", seats=1, is_leader=True, description="Leads."),
        Role(key="dev", title="Dev", seats=1, description="Builds."),
    ]
    grants = [
        SeatGrant(project_id=uuid4(), role_id=roles[0].id, marius_id=_ids[0]),
        SeatGrant(project_id=uuid4(), role_id=roles[1].id, marius_id=_ids[1]),
    ]
    liveness = {_ids[0]: Liveness.ONLINE, _ids[1]: Liveness.ONLINE}
    return roles, grants, liveness


# ── the five phases exist and nothing else does ───────────────────────────────────
def test_exactly_five_phases() -> None:
    assert [p.value for p in ProjectStatus] == [
        "setup",
        "planning",
        "operating",
        "maintaining",
        "closed",
    ]


# ── a full roster now lands in PLANNING, not straight into work (FR-002) ──────────
def test_full_online_roster_moves_setup_to_planning() -> None:
    roles, grants, liveness = _roster()
    project = Project(status=ProjectStatus.SETUP)

    assert recompute_active(project, roles, grants, liveness) is True
    assert project.status is ProjectStatus.PLANNING


def test_activation_is_one_way_and_idempotent() -> None:
    """A worker dropping offline afterwards must not drag the project back to setup."""
    roles, grants, liveness = _roster()
    project = Project(status=ProjectStatus.PLANNING)

    assert recompute_active(project, roles, grants, {}) is False
    assert project.status is ProjectStatus.PLANNING

    operating = Project(status=ProjectStatus.OPERATING)
    assert recompute_active(operating, roles, grants, liveness) is False
    assert operating.status is ProjectStatus.OPERATING


# ── the transition table (FR-004, FR-005) ─────────────────────────────────────────
@pytest.mark.parametrize(
    ("current", "target"),
    [
        (ProjectStatus.SETUP, ProjectStatus.PLANNING),
        (ProjectStatus.PLANNING, ProjectStatus.OPERATING),
        (ProjectStatus.OPERATING, ProjectStatus.MAINTAINING),
        (ProjectStatus.MAINTAINING, ProjectStatus.OPERATING),
        (ProjectStatus.OPERATING, ProjectStatus.CLOSED),
        (ProjectStatus.MAINTAINING, ProjectStatus.CLOSED),
    ],
)
def test_legal_phase_transitions(current: ProjectStatus, target: ProjectStatus) -> None:
    assert can_change_phase(current, target) is True
    assert_phase_transition(current, target)  # must not raise


@pytest.mark.parametrize(
    ("current", "target"),
    [
        (ProjectStatus.SETUP, ProjectStatus.OPERATING),  # no skipping the plan gate
        (ProjectStatus.PLANNING, ProjectStatus.CLOSED),
        (ProjectStatus.OPERATING, ProjectStatus.SETUP),  # never rolls back
        (ProjectStatus.PLANNING, ProjectStatus.SETUP),
        (ProjectStatus.CLOSED, ProjectStatus.OPERATING),  # closed is terminal (FR-005)
        (ProjectStatus.CLOSED, ProjectStatus.MAINTAINING),
    ],
)
def test_illegal_phase_transitions(current: ProjectStatus, target: ProjectStatus) -> None:
    assert can_change_phase(current, target) is False
    with pytest.raises(InvalidPhaseTransition):
        assert_phase_transition(current, target)


def test_a_phase_never_transitions_to_itself() -> None:
    for phase in ProjectStatus:
        assert can_change_phase(phase, phase) is False


# ── the FR-003 gate: no real task before the plan is approved ─────────────────────
@pytest.mark.parametrize(
    ("phase", "allowed"),
    [
        (ProjectStatus.SETUP, False),
        (ProjectStatus.PLANNING, False),
        (ProjectStatus.OPERATING, True),
        (ProjectStatus.MAINTAINING, True),
        (ProjectStatus.CLOSED, False),
    ],
)
def test_real_tasks_only_once_operating(phase: ProjectStatus, allowed: bool) -> None:
    assert accepts_real_tasks(phase) is allowed


def test_closed_is_the_only_read_only_phase() -> None:
    assert is_closed(ProjectStatus.CLOSED) is True
    for phase in ProjectStatus:
        if phase is not ProjectStatus.CLOSED:
            assert is_closed(phase) is False
