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

from armarius.application.use_cases.onboarding_brain import FIELD_PLAN
from armarius.application.use_cases.onboarding_session import (
    OnboardingBusy,
    OnboardingService,
    WorkspaceAgentUnavailable,
    plan_from_collected,
)
from armarius.application.use_cases.projects import (
    LEADER_ROLE_KEY,
    MEMBERS_ROLE_KEY,
    ProjectService,
)
from armarius.application.use_cases.workspace_agent import (
    WORKSPACE_AGENT_ROLE,
    WorkspaceAgentService,
)
from armarius.domain.entities.marius import Liveness, Marius
from armarius.domain.entities.onboarding import OnboardingStatus
from armarius.domain.entities.run import RunStatus
from armarius.domain.entities.workspace import Workspace
from armarius.infrastructure.adapters.registry import InMemoryAdapterRegistry
from tests.support.fakes import FakeAdapter, FakeUowFactory
from tests.support.prompts import field_plan_of


def _services(*, adapter: FakeAdapter | None = None):
    factory = FakeUowFactory()
    ws = Workspace(name="Studio", slug="studio", owner_user_id="u1")
    factory.store.workspaces[ws.id] = ws
    projects = ProjectService(factory)
    ws_agent = WorkspaceAgentService(factory)
    reg = InMemoryAdapterRegistry()
    if adapter is not None:
        reg.register(adapter)
    onboarding = OnboardingService(factory, projects, ws_agent, reg)
    return factory, onboarding, ws.id, adapter


# scripted WA turns — closures over the service so they post back through its callbacks ──


def _asks(onboarding: OnboardingService, key: str, question: str):
    async def driver(session_id, run_id) -> None:
        await onboarding.agent_post_question(
            session_id,
            {
                "key": key,
                "question": question,
                "options": [{"id": "1", "label": "An option"},
                            {"id": "other", "label": "Other (I'll type it)"}],
                "multi": False,
            },
            by_run=run_id,
        )

    return driver


def _completes(onboarding: OnboardingService, name: str, objective: str):
    async def driver(session_id, run_id) -> None:
        await onboarding.agent_post_complete(
            session_id,
            {
                "name": name,
                "objective": objective,
                "success_metrics": None,
                "target_date": None,
                "context": None,
            },
            by_run=run_id,
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
            adapter_type="fake",  # matches the FakeAdapter registered in _services
            liveness=Liveness.ONLINE,
        )
        await uow.mariuses.add(host)
        ws = await uow.workspaces.get(ws_id)
        ws.workspace_agent_id = host.id
        await uow.workspaces.update(ws)
        await uow.commit()


def _driving(factory: FakeUowFactory, session_id):
    """The run this chat's current turn belongs to — what a live agent would be speaking for."""
    return factory.store.onboardings[session_id].driving_run_id


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


async def test_complete_then_finalize_creates_the_project_and_its_two_rows() -> None:
    factory, onboarding, ws_id, adapter = _services(adapter=FakeAdapter())
    adapter.drivers.append(_completes(onboarding, "Live Plan", "Ship the thing"))
    await _ensure_then_online(onboarding, ws_id)
    session = await onboarding.start(ws_id)
    assert session.collected["phase"] == "complete"

    finalized = await onboarding.finalize(session.id, created_by_user_id="u1")

    assert finalized.status == OnboardingStatus.FINALIZED
    project = factory.store.projects[finalized.created_project_id]
    roles = [r for r in factory.store.roles.values() if r.project_id == project.id]
    # The same two rows every project gets, whoever created it — and no third one drafted by
    # the agent that ran the interview (FR-007l).
    assert {r.key for r in roles} == {LEADER_ROLE_KEY, MEMBERS_ROLE_KEY}
    assert sum(1 for r in roles if r.is_leader) == 1
    assert project.name == "Live Plan"
    assert project.objective == "Ship the thing"


async def test_finalize_without_a_draft_still_creates_a_valid_project() -> None:
    """A session whose draft is missing still finalizes to a project with a valid roster."""
    factory, onboarding, ws_id, adapter = _services(adapter=FakeAdapter())
    adapter.drivers.append(_asks(onboarding, "objective", "Q1"))  # a question, never a draft
    await _ensure_then_online(onboarding, ws_id)
    session = await onboarding.start(ws_id)

    finalized = await onboarding.finalize(session.id)

    project = factory.store.projects[finalized.created_project_id]
    roles = [r for r in factory.store.roles.values() if r.project_id == project.id]
    assert {r.key for r in roles} == {LEADER_ROLE_KEY, MEMBERS_ROLE_KEY}


async def test_agent_post_question_rejected_while_one_is_pending() -> None:
    """One question at a time — posting while unanswered raises (HTTP 409)."""
    factory, onboarding, ws_id, adapter = _services(adapter=FakeAdapter())
    adapter.drivers.append(_asks(onboarding, "objective", "Q1"))
    await _ensure_then_online(onboarding, ws_id)
    session = await onboarding.start(ws_id)  # a question is now pending

    with pytest.raises(OnboardingBusy):
        await onboarding.agent_post_question(
            session.id,
            {"question": "Q2?", "options": [{"id": "1", "label": "A"}], "multi": False},
            by_run=_driving(factory, session.id),
        )


def test_plan_from_collected_names_a_project_even_from_nothing() -> None:
    plan = plan_from_collected({})
    assert plan["name"]
    assert plan["objective"]


def test_nothing_about_the_team_survives_the_draft() -> None:
    """Whatever an agent puts in the draft, no role comes out of it (FR-007l).

    The three tests this replaces all guarded the same road: a model drafted worker roles, and
    the code had to defend against it mis-casting one as the leader, repeating a key, or
    leaving a description blank. None of that can happen now, because a drafted role has
    nowhere to go.
    """
    plan = plan_from_collected({"draft": {"roster": [
        {"title": "Business Analyst", "is_leader": True},
        {"title": "Developer", "is_leader": False, "description": "Builds the SPA."},
    ]}})

    assert "roles" not in plan and "roster" not in plan


# ── mọi lượt phải mang cả kế hoạch field, không riêng lượt đầu ───────────────────


class _RecordingAdapter(FakeAdapter):
    """`FakeAdapter`, nhưng giữ lại chữ đã thật sự gửi xuống từng lượt.

    Cần nó vì chỗ hỏng không nằm trong prompt nào cả — nó nằm ở **prompt nào được dùng cho lượt
    nào**. Đọc riêng từng hàm dựng prompt thì cả hai đều có vẻ ổn; chỉ khi biết lượt thứ hai dùng
    hàm nào mới thấy `worker_count` không bao giờ tới tay agent.
    """

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self.prompts: list[str] = []

    async def execute(self, ctx):
        self.prompts.append(ctx.prompt)
        return await super().execute(ctx)


async def test_every_turn_carries_the_whole_field_plan_not_just_the_first() -> None:
    """Lỗi người duyệt PR #272 tìm ra, giữ ở đúng tầng nó xảy ra.

    Buổi phỏng vấn hỏi một câu mỗi lượt. Lượt đầu dùng prompt mở đầu và chỉ hỏi câu thứ nhất; mọi
    lượt sau dùng prompt tiếp nối. Nên một field chỉ có trong prompt mở đầu là một field **không
    bao giờ được hỏi**. `worker_count` đúng như thế: nó vào prompt mở đầu, còn prompt tiếp nối vẫn
    liệt kê năm field và còn bảo *post draft sau `context`* — nên mọi dự án dựng bằng hỏi–đáp ra
    đời với đúng một chỗ cho người làm, y hệt trước khi có tính năng.

    Bài kiểm ở `test_onboarding_brain.py` giữ **nội dung** hai prompt. Bài này giữ thứ nó không
    thấy được: chữ **đã thật sự gửi đi** ở lượt thứ hai và thứ ba.
    """
    _, onboarding, ws_id, adapter = _services(adapter=_RecordingAdapter())
    adapter.drivers.extend([
        _asks(onboarding, "objective", "What are you building?"),
        _asks(onboarding, "name", "What should we call it?"),
        _asks(onboarding, "success_metrics", "How will you measure success?"),
    ])
    await _ensure_then_online(onboarding, ws_id)

    session = await onboarding.start(ws_id)
    session = await onboarding.answer(session.id, "A web app")
    await onboarding.answer(session.id, "Task Tracker")

    assert len(adapter.prompts) == 3, len(adapter.prompts)
    for turn, prompt in enumerate(adapter.prompts, start=1):
        # Đọc **phần kế hoạch field**, không phải cả prompt: mỗi tên field còn xuất hiện lần
        # nữa trong mẫu JSON của draft, nên tìm khắp prompt thì một kế hoạch đã rơi mất field
        # vẫn đạt — bản đầu của bài này xanh y nguyên khi tôi thử ngược lại.
        plan = field_plan_of(prompt)
        for field, _question in FIELD_PLAN:
            assert field in plan, f"kế hoạch field ở lượt {turn} thiếu {field}"
