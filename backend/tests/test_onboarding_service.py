"""OnboardingService — agent-driven, question-window project setup (#61).

Drives the use case against the in-memory fakes: the ``DeterministicBrain`` (a fixed plan of
tick-select questions that accumulates a real draft), the fresh-session-per-start rule, the
one-question-at-a-time agent callbacks, and ``finalize → ProjectService.create_project``.
"""

from __future__ import annotations

import pytest

from armarius.application.use_cases.onboarding_brain import (
    DeterministicBrain,
    is_free_text_option,
)
from armarius.application.use_cases.onboarding_session import (
    OnboardingBusy,
    OnboardingService,
    plan_from_collected,
)
from armarius.application.use_cases.projects import ProjectService
from armarius.application.use_cases.workspace_agent import (
    WORKSPACE_AGENT_ROLE,
    WorkspaceAgentService,
)
from armarius.domain.entities.onboarding import OnboardingError, OnboardingStatus
from armarius.domain.entities.workspace import Workspace
from tests.support.fakes import FakeUowFactory

# One answer per step key — walks the deterministic plan to completion.
_ANSWERS = {
    "objective": "A web app",
    "name": "Task Tracker",
    "roles": "Frontend, Backend",
    "metric": "Ship it",
    "target": "This month",
    "context": "No, that's it",
}


def _services() -> tuple[FakeUowFactory, OnboardingService, object]:
    factory = FakeUowFactory()
    ws = Workspace(name="Studio", slug="studio", owner_user_id="u1")
    factory.store.workspaces[ws.id] = ws
    projects = ProjectService(factory)
    ws_agent = WorkspaceAgentService(factory)
    onboarding = OnboardingService(factory, projects, ws_agent)
    return factory, onboarding, ws.id


async def _walk_to_complete(onboarding, session):
    """Answer every pending question with the canned answer until the draft is emitted."""
    while session.collected.get("pending_question") is not None:
        key = session.collected["pending_question"]["key"]
        session = await onboarding.answer(session.id, _ANSWERS[key])
    return session


# ── the deterministic brain (pure) ───────────────────────────────────────────────


def test_brain_starts_by_asking_the_objective_with_a_free_text_escape() -> None:
    collected = DeterministicBrain().start({})
    question = collected["pending_question"]
    assert collected["phase"] == "asking"
    assert question["key"] == "objective"
    assert any(is_free_text_option(o["label"]) for o in question["options"])


def test_brain_accumulates_answers_into_a_complete_draft() -> None:
    brain = DeterministicBrain()
    collected = brain.start({})
    seen_keys = []
    while collected.get("pending_question") is not None:
        key = collected["pending_question"]["key"]
        seen_keys.append(key)
        collected = brain.answer(collected, _ANSWERS[key])

    assert seen_keys == ["objective", "name", "roles", "metric", "target", "context"]
    assert collected["phase"] == "complete"
    draft = collected["draft"]
    assert draft["name"] == "Task Tracker"
    assert draft["objective"] == "A web app"
    titles = [r["title"] for r in draft["roster"]]
    assert titles[0] == "Project Leader"
    assert {"Frontend", "Backend"} <= set(titles)
    # exactly one leader, at least one worker
    assert sum(1 for r in draft["roster"] if r["is_leader"]) == 1


def test_roles_question_is_multi_select() -> None:
    brain = DeterministicBrain()
    collected = brain.start({})
    collected = brain.answer(collected, _ANSWERS["objective"])
    collected = brain.answer(collected, _ANSWERS["name"])
    assert collected["pending_question"]["key"] == "roles"
    assert collected["pending_question"]["multi"] is True


def test_plan_from_collected_defaults_to_a_valid_roster() -> None:
    plan = plan_from_collected({})
    assert any(r.is_leader for r in plan["roles"])
    assert any(not r.is_leader for r in plan["roles"])
    assert plan["name"]


# ── the use case ─────────────────────────────────────────────────────────────────


async def test_start_designates_agent_and_asks_first_question() -> None:
    factory, onboarding, ws_id = _services()

    session = await onboarding.start(ws_id)

    assert session.status == OnboardingStatus.OPEN
    assert session.collected["pending_question"]["key"] == "objective"
    assert session.transcript[0]["role"] == "agent"  # the first question, as text
    agents = [m for m in factory.store.mariuses.values() if m.role == WORKSPACE_AGENT_ROLE]
    assert len(agents) == 1


async def test_start_is_fresh_each_time_and_retires_the_prior_session() -> None:
    """Re-entering the agent flow starts clean — the stale open chat is abandoned (#61)."""
    _factory, onboarding, ws_id = _services()
    first = await onboarding.start(ws_id)

    second = await onboarding.start(ws_id)

    assert second.id != first.id
    assert (await onboarding.active_for(ws_id)).id == second.id
    prior = await onboarding.get(first.id)
    assert prior.status == OnboardingStatus.ABANDONED


async def test_answer_advances_and_reaches_a_draft() -> None:
    _factory, onboarding, ws_id = _services()
    session = await onboarding.start(ws_id)

    session = await _walk_to_complete(onboarding, session)

    assert session.collected["phase"] == "complete"
    draft = session.collected["draft"]
    assert draft["name"] == "Task Tracker"
    assert {"Frontend", "Backend"} <= {r["title"] for r in draft["roster"]}


async def test_finalize_creates_project_with_roster_and_fields() -> None:
    factory, onboarding, ws_id = _services()
    session = await onboarding.start(ws_id)
    session = await _walk_to_complete(onboarding, session)

    finalized = await onboarding.finalize(session.id, created_by_user_id="u1")

    assert finalized.status == OnboardingStatus.FINALIZED
    project = factory.store.projects[finalized.created_project_id]
    roles = [r for r in factory.store.roles.values() if r.project_id == project.id]
    assert sum(1 for r in roles if r.is_leader) == 1
    assert any(not r.is_leader for r in roles)
    assert project.name == "Task Tracker"
    assert project.objective == "A web app"


async def test_finalize_without_answers_still_creates_valid_project() -> None:
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


async def test_abandon_ends_session_and_blocks_further_answers() -> None:
    _factory, onboarding, ws_id = _services()
    session = await onboarding.start(ws_id)

    abandoned = await onboarding.abandon(session.id)
    assert abandoned.status == OnboardingStatus.ABANDONED

    with pytest.raises(OnboardingError):
        await onboarding.answer(session.id, "A web app")


async def test_active_for_returns_open_then_none() -> None:
    _factory, onboarding, ws_id = _services()
    assert await onboarding.active_for(ws_id) is None

    session = await onboarding.start(ws_id)
    assert (await onboarding.active_for(ws_id)).id == session.id

    await onboarding.abandon(session.id)
    assert await onboarding.active_for(ws_id) is None


# ── live Workspace-Agent runtime callbacks (agent-driven mode) ────────────────────


async def test_agent_post_question_is_rejected_while_one_is_pending() -> None:
    """One question at a time — posting while unanswered raises (HTTP 409)."""
    _factory, onboarding, ws_id = _services()
    session = await onboarding.start(ws_id)  # start already asked a question

    with pytest.raises(OnboardingBusy):
        await onboarding.agent_post_question(
            session.id,
            {"question": "Q?", "options": [{"id": "1", "label": "A"}], "multi": False},
        )


async def test_agent_post_complete_sets_the_draft() -> None:
    _factory, onboarding, ws_id = _services()
    session = await onboarding.start(ws_id)

    draft = {
        "name": "Live Plan",
        "objective": "Ship the thing",
        "roster": [
            {"key": "leader", "title": "Project Leader", "is_leader": True, "seats": 1},
            {"key": "frontend", "title": "Frontend", "is_leader": False, "seats": 1},
        ],
    }
    session = await onboarding.agent_post_complete(session.id, draft)

    assert session.collected["phase"] == "complete"
    assert session.collected["draft"]["name"] == "Live Plan"
    assert session.collected["pending_question"] is None
