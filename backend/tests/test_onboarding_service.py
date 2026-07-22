"""OnboardingService — a REAL Workspace Agent wakes the interview (#61, v3).

There is no scripted brain. ``start``/``answer`` wake the workspace's host agent through its
adapter; the guided agent posts its questions / final draft back via the agent-facing callbacks.
These tests drive that against the in-memory fakes with a ``FakeAdapter`` that scripts the WA's
behaviour during one bounded wake (post a question, post the draft, fail, raise). The hard rule
is covered too: an agent that is not ``ONLINE``/``WORKING`` (or whose wake fails) abandons the
session and raises ``WorkspaceAgentUnavailable`` — no fallback, at start or mid-interview.
"""

from __future__ import annotations

import pytest

from armarius.application.use_cases.onboarding_session import (
    OnboardingBusy,
    OnboardingService,
    WorkspaceAgentUnavailable,
    plan_from_collected,
)
from armarius.application.use_cases.projects import ProjectService
from armarius.application.use_cases.workspace_agent import (
    WORKSPACE_AGENT_ROLE,
    WorkspaceAgentService,
)
from armarius.domain.entities.marius import InviteStatus, Liveness, Marius
from armarius.domain.entities.onboarding import OnboardingStatus
from armarius.domain.entities.run import RunStatus
from armarius.domain.entities.workspace import Workspace
from armarius.infrastructure.adapters.registry import InMemoryAdapterRegistry
from tests.support.fakes import FakeAdapter, FakeUowFactory


def _services(*, adapter: FakeAdapter | None = None, base_url: str = "http://api.test"):
    factory = FakeUowFactory()
    ws = Workspace(name="Studio", slug="studio", owner_user_id="u1")
    factory.store.workspaces[ws.id] = ws
    projects = ProjectService(factory)
    ws_agent = WorkspaceAgentService(factory)
    reg = InMemoryAdapterRegistry()
    if adapter is not None:
        reg.register(adapter)
    onboarding = OnboardingService(factory, projects, ws_agent, reg, base_url)
    return factory, onboarding, ws.id, adapter


# scripted WA turns — closures over the service so they post back through its callbacks ──


def _asks(onboarding: OnboardingService, key: str, question: str):
    async def driver(session_id) -> None:
        await onboarding.agent_post_question(
            session_id,
            {
                "key": key,
                "question": question,
                "options": [{"id": "1", "label": "An option"},
                            {"id": "other", "label": "Other (I'll type it)"}],
                "multi": False,
            },
        )

    return driver


def _completes(onboarding: OnboardingService, name: str, objective: str):
    async def driver(session_id) -> None:
        await onboarding.agent_post_complete(
            session_id,
            {
                "name": name,
                "objective": objective,
                "success_metrics": None,
                "target_date": None,
                "context": None,
                "roster": [
                    {"key": "leader", "title": "Project Leader", "seats": 1, "is_leader": True},
                    {"key": "frontend", "title": "Frontend", "seats": 1, "is_leader": False},
                ],
            },
        )

    return driver


async def _ensure_then_online(onboarding: OnboardingService, ws_id) -> None:
    """Seat a real Workspace Agent (operator-invite model) and mark it ONLINE.

    Under #63 the WA is never lazy-created — it must be a real invited agent. We create +
    seat one directly here (the unit tests bypass the HTTP invite path) so start/answer see
    a ready host.
    """
    factory = onboarding._uow  # type: ignore[attr-defined]
    async with factory() as uow:
        host = Marius(
            workspace_id=ws_id,
            name="Workspace Agent",
            role=WORKSPACE_AGENT_ROLE,
            adapter_type="hermes_gateway",  # matches the FakeAdapter registered in _services
            liveness=Liveness.ONLINE,
            invite_status=InviteStatus.APPROVED,
            agent_token="arm_wa",
        )
        await uow.mariuses.add(host)
        ws = await uow.workspaces.get(ws_id)
        ws.workspace_agent_id = host.id
        await uow.workspaces.update(ws)
        await uow.commit()


async def _set_wa_liveness(factory: FakeUowFactory, ws_id, liveness: Liveness) -> None:
    async with factory() as uow:
        wa = next(
            m for m in await uow.mariuses.list_by_workspace(ws_id) if m.role == WORKSPACE_AGENT_ROLE
        )
        wa.liveness = liveness
        await uow.mariuses.update(wa)
        await uow.commit()


# ── the ready / wake-fail rule (the owner's core requirement) ────────────────────


async def test_start_with_offline_agent_raises_and_creates_no_session() -> None:
    factory, onboarding, ws_id, _adapter = _services(adapter=FakeAdapter())

    with pytest.raises(WorkspaceAgentUnavailable):
        await onboarding.start(ws_id)  # WA defaults to OFFLINE

    # No session left behind — onboarding cannot start without a ready agent.
    assert await onboarding.active_for(ws_id) is None
    assert not factory.store.onboardings


async def test_start_with_unknown_adapter_abandons_and_raises() -> None:
    """No adapter registered for the WA's runtime type → the wake fails; the session created
    just before the wake is abandoned and no live chat is left (no crash)."""
    factory, onboarding, ws_id, _adapter = _services(adapter=None)  # empty registry
    await _ensure_then_online(onboarding, ws_id)

    with pytest.raises(WorkspaceAgentUnavailable):
        await onboarding.start(ws_id)

    assert await onboarding.active_for(ws_id) is None
    # The session start opened before the wake failed is now abandoned (terminal, not live).
    assert all(s.status != OnboardingStatus.OPEN for s in factory.store.onboardings.values())


async def test_start_wake_fails_abandons_session_and_raises() -> None:
    _, onboarding, ws_id, _adapter = _services(adapter=FakeAdapter(status=RunStatus.FAILED))
    await _ensure_then_online(onboarding, ws_id)

    with pytest.raises(WorkspaceAgentUnavailable):
        await onboarding.start(ws_id)

    assert await onboarding.active_for(ws_id) is None  # abandoned on wake failure


async def test_start_adapter_raises_abandons_session_and_raises() -> None:
    _, onboarding, ws_id, _adapter = _services(
        adapter=FakeAdapter(raise_on_execute=RuntimeError("runtime down"))
    )
    await _ensure_then_online(onboarding, ws_id)

    with pytest.raises(WorkspaceAgentUnavailable):
        await onboarding.start(ws_id)
    assert await onboarding.active_for(ws_id) is None


async def test_answer_when_agent_went_offline_abandons_and_raises() -> None:
    factory, onboarding, ws_id, adapter = _services(adapter=FakeAdapter())
    adapter.drivers.append(_asks(onboarding, "objective", "What are you building?"))
    await _ensure_then_online(onboarding, ws_id)
    session = await onboarding.start(ws_id)
    assert session.collected["pending_question"]["question"] == "What are you building?"

    await _set_wa_liveness(factory, ws_id, Liveness.OFFLINE)  # drops offline mid-interview

    with pytest.raises(WorkspaceAgentUnavailable):
        await onboarding.answer(session.id, "A web app")

    assert (await onboarding.get(session.id)).status == OnboardingStatus.ABANDONED


async def test_answer_wake_fails_abandons_and_raises() -> None:
    _, onboarding, ws_id, adapter = _services(adapter=FakeAdapter())
    adapter.drivers.append(_asks(onboarding, "objective", "What are you building?"))
    await _ensure_then_online(onboarding, ws_id)
    session = await onboarding.start(ws_id)
    adapter.status = RunStatus.FAILED  # the answer wake now fails

    with pytest.raises(WorkspaceAgentUnavailable):
        await onboarding.answer(session.id, "A web app")

    assert (await onboarding.get(session.id)).status == OnboardingStatus.ABANDONED


async def test_start_succeeds_when_wa_is_working() -> None:
    """WORKING counts as ready too (not just ONLINE)."""
    factory, onboarding, ws_id, adapter = _services(adapter=FakeAdapter())
    adapter.drivers.append(_asks(onboarding, "objective", "What are you building?"))
    await _ensure_then_online(onboarding, ws_id)
    await _set_wa_liveness(factory, ws_id, Liveness.WORKING)

    session = await onboarding.start(ws_id)
    assert session.collected["pending_question"]["question"] == "What are you building?"


# ── the happy path: the real agent drives the interview ──────────────────────────


async def test_start_wakes_agent_and_its_first_question_lands() -> None:
    factory, onboarding, ws_id, adapter = _services(adapter=FakeAdapter())
    adapter.drivers.append(_asks(onboarding, "objective", "What are you building?"))
    await _ensure_then_online(onboarding, ws_id)

    session = await onboarding.start(ws_id)

    assert session.status == OnboardingStatus.OPEN
    assert session.collected["phase"] == "asking"
    assert session.collected["pending_question"]["question"] == "What are you building?"
    assert session.transcript[-1]["role"] == "agent"  # the question is in the scrollback
    wa = next(m for m in factory.store.mariuses.values() if m.role == WORKSPACE_AGENT_ROLE)
    assert factory.store.workspaces[ws_id].workspace_agent_id == wa.id  # designated host


async def test_answer_forwards_to_agent_and_advances_then_completes() -> None:
    _, onboarding, ws_id, adapter = _services(adapter=FakeAdapter())
    adapter.drivers.extend([
        _asks(onboarding, "objective", "What are you building?"),
        _asks(onboarding, "name", "What should we call it?"),
        _completes(onboarding, "Task Tracker", "A web app"),
    ])
    await _ensure_then_online(onboarding, ws_id)
    session = await onboarding.start(ws_id)

    session = await onboarding.answer(session.id, "A web app")
    assert session.collected["pending_question"]["question"] == "What should we call it?"

    session = await onboarding.answer(session.id, "Task Tracker")
    assert session.collected["phase"] == "complete"
    draft = session.collected["draft"]
    assert draft["name"] == "Task Tracker"
    assert draft["objective"] == "A web app"


async def test_start_is_fresh_each_time_and_retires_the_prior_session() -> None:
    """Re-entering the agent flow starts clean — the stale open chat is abandoned (#61)."""
    _, onboarding, ws_id, adapter = _services(adapter=FakeAdapter())
    adapter.drivers.append(_asks(onboarding, "objective", "Q1"))
    await _ensure_then_online(onboarding, ws_id)
    first = await onboarding.start(ws_id)

    adapter.drivers.append(_asks(onboarding, "objective", "Q1"))  # re-arm for the 2nd start
    second = await onboarding.start(ws_id)

    assert second.id != first.id
    assert (await onboarding.active_for(ws_id)).id == second.id
    assert (await onboarding.get(first.id)).status == OnboardingStatus.ABANDONED


# ── finalize + the agent callbacks ───────────────────────────────────────────────


async def test_complete_then_finalize_creates_project_with_roster() -> None:
    factory, onboarding, ws_id, adapter = _services(adapter=FakeAdapter())
    adapter.drivers.append(_completes(onboarding, "Live Plan", "Ship the thing"))
    await _ensure_then_online(onboarding, ws_id)
    session = await onboarding.start(ws_id)
    assert session.collected["phase"] == "complete"

    finalized = await onboarding.finalize(session.id, created_by_user_id="u1")

    assert finalized.status == OnboardingStatus.FINALIZED
    project = factory.store.projects[finalized.created_project_id]
    roles = [r for r in factory.store.roles.values() if r.project_id == project.id]
    assert sum(1 for r in roles if r.is_leader) == 1
    assert any(not r.is_leader for r in roles)
    assert project.name == "Live Plan"
    assert project.objective == "Ship the thing"


async def test_finalize_without_a_draft_still_creates_a_valid_project() -> None:
    """A session whose draft is missing still finalizes to a valid leader + worker roster."""
    factory, onboarding, ws_id, adapter = _services(adapter=FakeAdapter())
    adapter.drivers.append(_asks(onboarding, "objective", "Q1"))  # a question, never a draft
    await _ensure_then_online(onboarding, ws_id)
    session = await onboarding.start(ws_id)

    finalized = await onboarding.finalize(session.id)

    project = factory.store.projects[finalized.created_project_id]
    roles = [r for r in factory.store.roles.values() if r.project_id == project.id]
    assert any(r.is_leader for r in roles)
    assert any(not r.is_leader for r in roles)


async def test_agent_post_question_rejected_while_one_is_pending() -> None:
    """One question at a time — posting while unanswered raises (HTTP 409)."""
    _, onboarding, ws_id, adapter = _services(adapter=FakeAdapter())
    adapter.drivers.append(_asks(onboarding, "objective", "Q1"))
    await _ensure_then_online(onboarding, ws_id)
    session = await onboarding.start(ws_id)  # a question is now pending

    with pytest.raises(OnboardingBusy):
        await onboarding.agent_post_question(
            session.id,
            {"question": "Q2?", "options": [{"id": "1", "label": "A"}], "multi": False},
        )


def test_plan_from_collected_defaults_to_a_valid_roster() -> None:
    plan = plan_from_collected({})
    assert any(r.is_leader for r in plan["roles"])
    assert any(not r.is_leader for r in plan["roles"])
    assert plan["name"]


def test_plan_from_collected_always_injects_canonical_project_leader() -> None:
    """A weak agent that casts a worker as the leader still yields a canonical Project Leader;
    the mis-cast role is dropped and the real workers survive — so the project always has a real
    PL, never a mislabeled one (#110)."""
    plan = plan_from_collected({"draft": {"roster": [
        {"title": "Business Analyst", "is_leader": True},
        {"title": "Developer", "is_leader": False},
    ]}})
    roles = plan["roles"]
    leaders = [r for r in roles if r.is_leader]
    assert len(leaders) == 1
    assert leaders[0].title == "Project Leader"  # canonical — not the agent's "Business Analyst"
    # The mis-cast "Business Analyst" is dropped; "Developer" survives as a worker.
    assert {r.title for r in roles if not r.is_leader} == {"Developer"}


def test_plan_from_collected_gives_every_role_a_description() -> None:
    """Spec 03 §3.1 wants every project role to carry a description the wake/leader-chat prompts
    can show. The agent's own description is kept verbatim; a worker it left blank falls back to a
    title-derived line — so NO role (leader or worker) lands with an empty description (#112)."""
    plan = plan_from_collected({"draft": {"roster": [
        {"title": "Frontend", "description": "Builds the SPA."},  # agent supplied → kept
        {"title": "Backend"},                                     # agent omitted → fallback
    ]}})
    roles = plan["roles"]
    assert all(r.description.strip() for r in roles)  # nobody empty, leader included
    by_title = {r.title: r.description for r in roles}
    assert by_title["Frontend"] == "Builds the SPA."   # verbatim passthrough
    assert "Backend" in by_title["Backend"]            # title-derived fallback, non-empty
