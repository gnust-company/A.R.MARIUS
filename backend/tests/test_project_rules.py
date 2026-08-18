"""Pure project rules — roster validation + the activation rule (LLD §3.1, §4)."""

from __future__ import annotations

from uuid import UUID, uuid4

import pytest

from armarius.domain.entities.marius import Liveness
from armarius.domain.entities.project import Project, ProjectStatus
from armarius.domain.entities.role import Role
from armarius.domain.entities.seat_grant import SeatGrant
from armarius.domain.services.project_rules import (
    InvalidProjectPlan,
    recompute_active,
    should_activate,
    validate_plan,
)


def _leader() -> Role:
    return Role(key="leader", title="Leader", seats=1, is_leader=True,
                description="Leads the project.")


def _worker(key: str = "backend", seats: int = 1) -> Role:
    return Role(key=key, title=key.title(), seats=seats, description="Does the work.")


def _seat(role: Role, marius_id: UUID) -> SeatGrant:
    """A seat points at the role row, not at its key (T199)."""
    return SeatGrant(project_id=uuid4(), role_id=role.id, marius_id=marius_id)


# ── validate_plan ────────────────────────────────────────────────────────────


def test_valid_plan_passes() -> None:
    validate_plan([_leader(), _worker()])  # no raise


def test_plan_needs_exactly_one_leader() -> None:
    with pytest.raises(InvalidProjectPlan):
        validate_plan([_worker()])  # zero leaders
    with pytest.raises(InvalidProjectPlan):
        validate_plan([_leader(), _leader(), _worker()])  # two leaders


def test_leader_must_have_one_seat() -> None:
    bad_leader = Role(key="leader", title="Leader", seats=2, is_leader=True)
    with pytest.raises(InvalidProjectPlan):
        validate_plan([bad_leader, _worker()])


def test_plan_needs_a_worker() -> None:
    with pytest.raises(InvalidProjectPlan):
        validate_plan([_leader()])


def test_plan_needs_a_description_on_every_role() -> None:
    # Composition is valid, but a role has no (or blank) description → rejected (#112).
    with pytest.raises(InvalidProjectPlan):
        validate_plan([_leader(), Role(key="qa", title="QA", seats=1, description="")])
    with pytest.raises(InvalidProjectPlan):
        validate_plan([  # whitespace-only counts as missing
            Role(key="leader", title="Leader", seats=1, is_leader=True, description="  "),
            _worker(),
        ])


# ── activation rule ──────────────────────────────────────────────────────────


def test_not_active_until_seats_filled() -> None:
    lead_role, work_role = _leader(), _worker(seats=2)
    roles = [lead_role, work_role]
    m1 = uuid4()
    grants = [_seat(lead_role, uuid4()),
              _seat(work_role, m1)]  # only 1 of 2 worker seats
    liveness = {g.marius_id: Liveness.ONLINE for g in grants}
    assert should_activate(roles, grants, liveness) is False


def test_not_active_until_every_seat_online() -> None:
    lead_role, work_role = _leader(), _worker()
    roles = [lead_role, work_role]
    lead, back = uuid4(), uuid4()
    grants = [_seat(lead_role, lead), _seat(work_role, back)]
    liveness = {lead: Liveness.ONLINE, back: Liveness.CHECKING}  # one not online
    assert should_activate(roles, grants, liveness) is False


def test_active_when_all_seats_filled_and_online() -> None:
    lead_role, work_role = _leader(), _worker()
    roles = [lead_role, work_role]
    lead, back = uuid4(), uuid4()
    grants = [_seat(lead_role, lead), _seat(work_role, back)]
    liveness = {lead: Liveness.ONLINE, back: Liveness.ONLINE}
    assert should_activate(roles, grants, liveness) is True


def test_a_vacated_seat_is_simply_not_there() -> None:
    """T199 — không còn dòng *đã thu hồi* để phải lọc: ghế trả lại là ghế biến mất."""
    lead_role, work_role = _leader(), _worker()
    roles = [lead_role, work_role]
    lead, back = uuid4(), uuid4()
    grants = [_seat(lead_role, lead)]  # ghế thợ đã được trả lại
    liveness = {lead: Liveness.ONLINE, back: Liveness.ONLINE}
    assert should_activate(roles, grants, liveness) is False


def test_a_renamed_role_does_not_empty_its_own_seats() -> None:
    """T199 — ghế trỏ vào *dòng vai*, nên đổi mã vai không làm ghế rỗng đi."""
    lead_role, work_role = _leader(), _worker()
    roles = [lead_role, work_role]
    lead, back = uuid4(), uuid4()
    grants = [_seat(lead_role, lead), _seat(work_role, back)]
    work_role.key = "server"  # người chủ đổi mã vai
    liveness = {lead: Liveness.ONLINE, back: Liveness.ONLINE}
    assert should_activate(roles, grants, liveness) is True


def test_recompute_flips_setup_to_planning_once() -> None:
    """Spec 001 FR-002: a full, online roster opens the *planning* gate, not the work."""
    project = Project(status=ProjectStatus.SETUP)
    roles = [_leader(), _worker()]
    lead, back = uuid4(), uuid4()
    grants = [_seat(roles[0], lead), _seat(roles[1], back)]
    online = {lead: Liveness.ONLINE, back: Liveness.ONLINE}

    assert recompute_active(project, roles, grants, online) is True
    assert project.status == ProjectStatus.PLANNING

    # idempotent: a second call does not "re-activate"
    assert recompute_active(project, roles, grants, online) is False


def test_activation_never_rolls_back_when_agent_drops() -> None:
    project = Project(status=ProjectStatus.PLANNING)
    roles = [_leader(), _worker()]
    lead, back = uuid4(), uuid4()
    grants = [_seat(roles[0], lead), _seat(roles[1], back)]
    dropped = {lead: Liveness.ONLINE, back: Liveness.OFFLINE}

    assert recompute_active(project, roles, grants, dropped) is False
    assert project.status == ProjectStatus.PLANNING  # one-way, never rolls back
