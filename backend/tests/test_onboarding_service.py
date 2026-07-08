"""OnboardingService — agent-assisted project setup (LLD §2.10, Sprint 7 / Phase G).

Drives the use case against the in-memory fakes: the scripted brain, the session FSM, and
the ``finalize → ProjectService.create_project`` materialisation (a real ``setup`` project
+ roster satisfying the hard one-leader-plus-workers rule).
"""

from __future__ import annotations

import pytest

from armarius.application.use_cases.onboarding_session import (
    OnboardingService,
    is_confirmation,
    plan_from_collected,
    propose_plan,
)
from armarius.application.use_cases.projects import ProjectService
from armarius.application.use_cases.workspace_agent import (
    WORKSPACE_AGENT_ROLE,
    WorkspaceAgentService,
)
from armarius.domain.entities.onboarding import OnboardingError, OnboardingStatus
from armarius.domain.entities.workspace import Workspace
from tests.support.fakes import FakeUowFactory


def _services() -> tuple[FakeUowFactory, OnboardingService, object]:
    factory = FakeUowFactory()
    ws = Workspace(name="Studio", slug="studio", owner_user_id="u1")
    factory.store.workspaces[ws.id] = ws
    projects = ProjectService(factory)
    ws_agent = WorkspaceAgentService(factory)
    onboarding = OnboardingService(factory, projects, ws_agent)
    return factory, onboarding, ws.id


# ── the scripted brain (pure) ────────────────────────────────────────────────────


def test_propose_plan_matches_keywords_and_always_has_leader() -> None:
    plan = propose_plan("Build a react frontend and a node backend api")
    titles = [r["title"] for r in plan["roles"]]
    assert "Project Leader" in titles
    assert "Frontend" in titles
    assert "Backend" in titles
    leaders = [r for r in plan["roles"] if r["is_leader"]]
    workers = [r for r in plan["roles"] if not r["is_leader"]]
    assert len(leaders) == 1
    assert len(workers) >= 1


def test_propose_plan_defaults_to_fe_be_when_no_keyword() -> None:
    plan = propose_plan("something generic")
    titles = {r["title"] for r in plan["roles"]}
    assert titles >= {"Project Leader", "Frontend", "Backend"}


def test_project_name_strips_stopwords() -> None:
    assert propose_plan("build a web shop")["project_name"] == "Web Shop"
    assert propose_plan("")["project_name"] == "New Project"


def test_is_confirmation() -> None:
    assert is_confirmation("looks good!")
    assert is_confirmation("yes, create it")
    assert not is_confirmation("no, add a design role")
    assert not is_confirmation("change the backend to data")


def test_plan_from_collected_defaults_valid() -> None:
    plan = plan_from_collected({})
    leaders = [r for r in plan["roles"] if r.is_leader]
    workers = [r for r in plan["roles"] if not r.is_leader]
    assert len(leaders) == 1
    assert len(workers) >= 1
    assert plan["name"]


# ── the use case ─────────────────────────────────────────────────────────────────


async def test_start_designates_agent_and_greets() -> None:
    factory, onboarding, ws_id = _services()

    session = await onboarding.start(ws_id)

    assert session.status == OnboardingStatus.OPEN
    assert session.transcript[0]["role"] == "agent"  # the greeting
    # The Workspace Agent was designated as part of opening the chat.
    agents = [m for m in factory.store.mariuses.values() if m.role == WORKSPACE_AGENT_ROLE]
    assert len(agents) == 1


async def test_message_proposes_roster_then_confirm_sets_ready() -> None:
    _factory, onboarding, ws_id = _services()
    session = await onboarding.start(ws_id)

    shaped = await onboarding.message(
        session.id, "Build a react frontend with a python backend api"
    )
    agent_turns = [t for t in shaped.transcript if t["role"] == "agent"]
    assert "Frontend" in agent_turns[-1]["text"]
    assert "Backend" in agent_turns[-1]["text"]
    titles = {r["title"] for r in shaped.collected["roles"]}
    assert {"Project Leader", "Frontend", "Backend"} <= titles

    locked = await onboarding.message(session.id, "looks good")
    assert locked.collected["ready"] is True


# ── the brain accumulates the plan across turns (#55) ────────────────────────────
# Regression: the brain used to re-derive the plan from the latest message alone and
# overwrite `collected`, so every reply looked the same and roles added earlier were
# forgotten ("100 lần như 1"). The plan must accumulate: a later message merges into the
# running plan instead of replacing it, and explicit add/remove/swap are honoured.


def _worker_titles(collected: dict) -> list[str]:
    return [r["title"] for r in collected.get("roles", []) if not r["is_leader"]]


async def test_roles_accumulate_across_turns_instead_of_being_replaced() -> None:
    """Adding a role in a later turn must keep the roles agreed earlier (#55)."""
    _factory, onboarding, ws_id = _services()
    session = await onboarding.start(ws_id)
    await onboarding.message(session.id, "I want a frontend app")

    session = await onboarding.message(session.id, "now add a backend api")

    assert _worker_titles(session.collected) == ["Frontend", "Backend"]


async def test_project_name_is_stable_once_set() -> None:
    """The project name must not flip to a name derived from each new message (#55).
    The first objective sets the name; later refinements keep it."""
    _factory, onboarding, ws_id = _services()
    session = await onboarding.start(ws_id)
    session = await onboarding.message(session.id, "Build a task tracker with a frontend")
    first_name = session.collected["project_name"]
    assert first_name == "Task Tracker Frontend"

    # A follow-up that adds a role must not rename the project after the latest message.
    session = await onboarding.message(session.id, "also add a backend api")

    assert session.collected["project_name"] == first_name


async def test_remove_drops_a_role_from_the_plan() -> None:
    """'remove <role>' must actually drop it — not silently re-propose it (#55)."""
    _factory, onboarding, ws_id = _services()
    session = await onboarding.start(ws_id)
    session = await onboarding.message(session.id, "I want a frontend and a backend")
    assert set(_worker_titles(session.collected)) == {"Frontend", "Backend"}

    session = await onboarding.message(session.id, "remove the backend")

    assert _worker_titles(session.collected) == ["Frontend"]
    # The reply acknowledges the removal: Backend no longer appears as a seat line.
    agent_turns = [t for t in session.transcript if t["role"] == "agent"]
    seat_lines = [ln for ln in agent_turns[-1]["text"].splitlines() if ln.strip().startswith("•")]
    assert all("Backend" not in ln for ln in seat_lines)


async def test_swap_replaces_one_role_with_another() -> None:
    """'swap X for Y' / 'replace X with Y' exchanges roles in the running plan (#55)."""
    _factory, onboarding, ws_id = _services()
    session = await onboarding.start(ws_id)
    session = await onboarding.message(session.id, "I need a frontend")
    assert _worker_titles(session.collected) == ["Frontend"]

    session = await onboarding.message(session.id, "swap the frontend for a design role")

    assert _worker_titles(session.collected) == ["Design"]


async def test_add_introduces_a_new_named_role() -> None:
    """'add <role>' introduces a role even when its keyword isn't in the objective (#55)."""
    _factory, onboarding, ws_id = _services()
    session = await onboarding.start(ws_id)
    session = await onboarding.message(session.id, "build a web app")  # → Frontend + Backend
    before = set(_worker_titles(session.collected))

    session = await onboarding.message(session.id, "add a QA reviewer")

    after = set(_worker_titles(session.collected))
    assert "QA / Reviewer" in after
    assert before <= after  # existing roles kept



async def test_finalize_creates_project_with_roster() -> None:
    factory, onboarding, ws_id = _services()
    session = await onboarding.start(ws_id)
    await onboarding.message(session.id, "Build a react frontend with a backend api")

    finalized = await onboarding.finalize(session.id, created_by_user_id="u1")

    assert finalized.status == OnboardingStatus.FINALIZED
    assert finalized.created_project_id is not None
    # The project exists with a roster that satisfies the hard rule.
    project = factory.store.projects[finalized.created_project_id]
    roles = [r for r in factory.store.roles.values() if r.project_id == project.id]
    leaders = [r for r in roles if r.is_leader]
    workers = [r for r in roles if not r.is_leader]
    assert len(leaders) == 1
    assert len(workers) >= 1
    assert project.objective  # the objective carried through


async def test_finalize_without_objective_still_creates_valid_project() -> None:
    factory, onboarding, ws_id = _services()
    session = await onboarding.start(ws_id)

    finalized = await onboarding.finalize(session.id)

    project = factory.store.projects[finalized.created_project_id]
    roles = [r for r in factory.store.roles.values() if r.project_id == project.id]
    assert any(r.is_leader for r in roles)
    assert any(not r.is_leader for r in roles)


async def test_finalize_twice_raises() -> None:
    _factory, onboarding, ws_id = _services()
    session = await onboarding.start(ws_id)
    await onboarding.finalize(session.id)

    with pytest.raises(OnboardingError):
        await onboarding.finalize(session.id)


async def test_abandon_ends_session_and_blocks_further_messages() -> None:
    _factory, onboarding, ws_id = _services()
    session = await onboarding.start(ws_id)

    abandoned = await onboarding.abandon(session.id)
    assert abandoned.status == OnboardingStatus.ABANDONED

    with pytest.raises(OnboardingError):
        await onboarding.message(session.id, "hello again")


async def test_active_for_returns_open_then_none() -> None:
    _factory, onboarding, ws_id = _services()
    assert await onboarding.active_for(ws_id) is None

    session = await onboarding.start(ws_id)
    assert (await onboarding.active_for(ws_id)).id == session.id

    await onboarding.abandon(session.id)
    assert await onboarding.active_for(ws_id) is None
