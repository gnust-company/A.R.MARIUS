"""Pure project rules — roster validation + the activation rule (LLD §3.1, §4)."""

from __future__ import annotations

from uuid import uuid4

import pytest

from armarius.domain.entities.marius import Liveness
from armarius.domain.entities.project import Project, ProjectStatus
from armarius.domain.entities.role import Role
from armarius.domain.entities.seat_grant import SeatGrant, SeatGrantStatus
from armarius.domain.services.project_rules import (
    InvalidProjectPlan,
    recompute_active,
    should_activate,
    validate_plan,
)


def _leader() -> Role:
    return Role(key="leader", title="Leader", seats=1, is_leader=True)


def _worker(key: str = "backend", seats: int = 1) -> Role:
    return Role(key=key, title=key.title(), seats=seats)


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


# ── activation rule ──────────────────────────────────────────────────────────


def test_not_active_until_seats_filled() -> None:
    roles = [_leader(), _worker(seats=2)]
    m1 = uuid4()
    grants = [SeatGrant(role_key="leader", marius_id=uuid4()),
              SeatGrant(role_key="backend", marius_id=m1)]  # only 1 of 2 worker seats
    liveness = {g.marius_id: Liveness.ONLINE for g in grants}
    assert should_activate(roles, grants, liveness) is False


def test_not_active_until_every_seat_online() -> None:
    roles = [_leader(), _worker()]
    lead, back = uuid4(), uuid4()
    grants = [SeatGrant(role_key="leader", marius_id=lead),
              SeatGrant(role_key="backend", marius_id=back)]
    liveness = {lead: Liveness.ONLINE, back: Liveness.CHECKING}  # one not online
    assert should_activate(roles, grants, liveness) is False


def test_active_when_all_seats_filled_and_online() -> None:
    roles = [_leader(), _worker()]
    lead, back = uuid4(), uuid4()
    grants = [SeatGrant(role_key="leader", marius_id=lead),
              SeatGrant(role_key="backend", marius_id=back)]
    liveness = {lead: Liveness.ONLINE, back: Liveness.ONLINE}
    assert should_activate(roles, grants, liveness) is True


def test_revoked_grant_does_not_count() -> None:
    roles = [_leader(), _worker()]
    lead, back = uuid4(), uuid4()
    grants = [
        SeatGrant(role_key="leader", marius_id=lead),
        SeatGrant(role_key="backend", marius_id=back, status=SeatGrantStatus.REVOKED),
    ]
    liveness = {lead: Liveness.ONLINE, back: Liveness.ONLINE}
    assert should_activate(roles, grants, liveness) is False


def test_recompute_flips_setup_to_active_once() -> None:
    project = Project(status=ProjectStatus.SETUP)
    roles = [_leader(), _worker()]
    lead, back = uuid4(), uuid4()
    grants = [SeatGrant(role_key="leader", marius_id=lead),
              SeatGrant(role_key="backend", marius_id=back)]
    online = {lead: Liveness.ONLINE, back: Liveness.ONLINE}

    assert recompute_active(project, roles, grants, online) is True
    assert project.status == ProjectStatus.ACTIVE

    # idempotent: a second call does not "re-activate"
    assert recompute_active(project, roles, grants, online) is False


def test_active_never_rolls_back_when_agent_drops() -> None:
    project = Project(status=ProjectStatus.ACTIVE)
    roles = [_leader(), _worker()]
    lead, back = uuid4(), uuid4()
    grants = [SeatGrant(role_key="leader", marius_id=lead),
              SeatGrant(role_key="backend", marius_id=back)]
    dropped = {lead: Liveness.ONLINE, back: Liveness.OFFLINE}

    assert recompute_active(project, roles, grants, dropped) is False
    assert project.status == ProjectStatus.ACTIVE  # stays active
