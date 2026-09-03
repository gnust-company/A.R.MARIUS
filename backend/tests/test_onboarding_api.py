"""Contract-conformance — Onboarding endpoints (#61, v3).

The Workspace Agent is a REAL runtime. With no agent enrolled/online (the default), ``start``
returns **409** — there is no scripted fallback. The happy path is exercised by wiring a
``FakeAdapter`` into the app's registry and marking the host agent ONLINE, then walking
start → answer → finalize against the real app wiring (container, error handlers, schemas).
Workspace scoping (cross-workspace 404) is checked on a real session.
"""

from __future__ import annotations

from uuid import UUID

from httpx import ASGITransport, AsyncClient

from armarius.domain.entities.marius import Liveness
from armarius.infrastructure.persistence.unit_of_work import make_uow
from armarius.main import app
from tests.support.fakes import FakeAdapter


async def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def _register(c: AsyncClient, email: str) -> tuple[str, str]:
    r = await c.post(
        "/auth/register",
        json={"email": email, "full_name": "Patron", "password": "password1234"},
    )
    token = r.json()["tokens"]["access_token"]
    ws = await c.get("/v1/workspaces", headers={"Authorization": f"Bearer {token}"})
    return token, ws.json()[0]["id"]


async def _online_wa(ws_id: str) -> None:
    """Seat a real Workspace Agent (operator-invite, #63) and flip it ONLINE for the happy path.

    The WA is never lazy-created anymore — we create an agent directly and seat it as host
    (the unit-style bypass of the HTTP invite path), so onboarding's turn finds a ready host
    whose adapter_type the wired FakeAdapter will satisfy.
    """
    from armarius.domain.entities.marius import Marius
    from tests.support.agents import ready_workplace

    ws_uuid = UUID(ws_id)
    # Placed, like every agent the product can make (FR-007f). A workspace agent with nowhere
    # to work cannot be handed a turn, and the interview's turn is a run like any other.
    workplace_id = UUID(await ready_workplace(ws_uuid))
    async with make_uow() as uow:
        host = Marius(
            workspace_id=ws_uuid,
            name="Workspace Agent",
            role="Workspace Agent",
            adapter_type="fake",
            liveness=Liveness.ONLINE,
        )
        created = await uow.mariuses.add(host)
        await uow.placements.attach(created.id, ws_uuid, workplace_id)
        ws = await uow.workspaces.get(ws_uuid)
        assert ws is not None
        ws.workspace_agent_id = host.id
        await uow.workspaces.update(ws)
        await uow.commit()


def _wire_agent(drivers: list) -> FakeAdapter:
    """Swap the app's fake adapter for one that scripts the WA's turns."""
    fake = FakeAdapter(drivers=drivers)
    app.state.container.registry._adapters["fake"] = fake  # type: ignore[attr-defined]
    return fake


def _ask(container, key: str, question: str):
    async def driver(session_id, run_id) -> None:
        await container.onboarding.agent_post_question(
            session_id,
            {"key": key, "question": question,
             "options": [{"id": "1", "label": "A web app"}, {"id": "other", "label": "Other"}],
             "multi": False},
            by_run=run_id,
        )

    return driver


def _complete(container, name: str, objective: str):
    async def driver(session_id, run_id) -> None:
        await container.onboarding.agent_post_complete(
            session_id,
            {"name": name, "objective": objective, "success_metrics": None,
             "target_date": None, "context": None,
             "roster": [
                 {"key": "leader", "title": "Project Leader", "seats": 1, "is_leader": True,
                  "description": "Leads."},
                 {"key": "frontend", "title": "Frontend", "seats": 1, "is_leader": False,
                  "description": "Builds the UI."},
             ]},
            by_run=run_id,
        )

    return driver


# ── the not-ready rule (the default — no runtime enrolled) ───────────────────────


async def test_start_returns_409_when_workspace_agent_is_not_online() -> None:
    async with await _client() as c:
        token, ws_id = await _register(c, "onboffline@armarius.dev")
        h = {"Authorization": f"Bearer {token}"}

        started = await c.post(f"/v1/workspaces/{ws_id}/onboarding", headers=h)

        assert started.status_code == 409
        assert "workspace agent" in started.json()["detail"].lower()
        # No session was created.
        active = await c.get(f"/v1/workspaces/{ws_id}/onboarding/active", headers=h)
        assert active.status_code == 404


# ── the happy path through the real app with a wired fake agent ──────────────────


async def test_onboarding_start_answer_finalize_creates_project() -> None:
    async with await _client() as c:
        token, ws_id = await _register(c, "onb1@armarius.dev")
        h = {"Authorization": f"Bearer {token}"}
        await _online_wa(ws_id)
        container = app.state.container
        _wire_agent([
            _ask(container, "objective", "What are you building?"),
            _complete(container, "Task Tracker", "A web app"),
        ])

        started = await c.post(f"/v1/workspaces/{ws_id}/onboarding", headers=h)
        assert started.status_code == 201, started.text
        session = started.json()
        assert session["status"] == "open"
        assert session["collected"]["pending_question"]["key"] == "objective"
        sid = session["id"]

        answered = await c.post(
            f"/v1/onboarding/{sid}/answer", headers=h, json={"answer": "A web app"}
        )
        assert answered.status_code == 200, answered.text
        session = answered.json()
        assert session["collected"]["phase"] == "complete"
        assert session["collected"]["draft"]["name"] == "Task Tracker"

        finalized = await c.post(f"/v1/onboarding/{sid}/finalize", headers=h)
        assert finalized.status_code == 200, finalized.text
        body = finalized.json()
        assert body["status"] == "finalized"
        pid = body["created_project_id"]
        assert pid is not None

        roster = await c.get(f"/v1/projects/{pid}/roster", headers=h)
        assert roster.status_code == 200
        roles = roster.json()
        assert any(r["is_leader"] for r in roles)
        assert any(not r["is_leader"] for r in roles)


async def test_answer_mid_interview_when_agent_drops_offline_is_409() -> None:
    async with await _client() as c:
        token, ws_id = await _register(c, "onbdrop@armarius.dev")
        h = {"Authorization": f"Bearer {token}"}
        await _online_wa(ws_id)
        container = app.state.container
        _wire_agent([_ask(container, "objective", "What are you building?")])

        sid = (await c.post(f"/v1/workspaces/{ws_id}/onboarding", headers=h)).json()["id"]

        # The agent goes offline between the patron's turns.
        async with make_uow() as uow:
            ws = await uow.workspaces.get(UUID(ws_id))
            assert ws is not None and ws.workspace_agent_id is not None
            wa = await uow.mariuses.get(ws.workspace_agent_id)
            assert wa is not None
            wa.liveness = Liveness.OFFLINE
            await uow.mariuses.update(wa)
            await uow.commit()

        again = await c.post(
            f"/v1/onboarding/{sid}/answer", headers=h, json={"answer": "A web app"}
        )
        assert again.status_code == 409
        assert "workspace agent" in again.json()["detail"].lower()


# ── workspace scoping ────────────────────────────────────────────────────────────


async def test_onboarding_cross_workspace_is_404() -> None:
    async with await _client() as c:
        token_a, ws_a = await _register(c, "onb_a@armarius.dev")
        token_b, _ws_b = await _register(c, "onb_b@armarius.dev")
        h_a = {"Authorization": f"Bearer {token_a}"}
        h_b = {"Authorization": f"Bearer {token_b}"}
        await _online_wa(ws_a)
        container = app.state.container
        _wire_agent([_ask(container, "objective", "What are you building?")])

        sid = (await c.post(f"/v1/workspaces/{ws_a}/onboarding", headers=h_a)).json()["id"]

        # Another user cannot read, answer, or finalize the session.
        assert (await c.get(f"/v1/onboarding/{sid}", headers=h_b)).status_code == 404
        assert (
            await c.post(f"/v1/onboarding/{sid}/answer", headers=h_b, json={"answer": "x"})
        ).status_code == 404
        assert (await c.post(f"/v1/onboarding/{sid}/finalize", headers=h_b)).status_code == 404


# ── the interview on the daemon road, through the real wiring ────────────────────


async def _the_interview_run(ws_id: str):
    """The one run the interview opened, read back from the real table."""
    from sqlalchemy import select

    from armarius.infrastructure.database.engine import get_sessionmaker
    from armarius.infrastructure.database.models import MariusModel, RunModel

    async with get_sessionmaker()() as session:
        row = (
            await session.execute(
                select(RunModel)
                .join(MariusModel, MariusModel.id == RunModel.marius_id)
                .where(MariusModel.workspace_id == UUID(ws_id))
            )
        ).scalars().all()
    assert len(row) == 1, f"mong đúng một lượt chạy, có {len(row)}"
    return row[0]


async def _machine_of(workplace_id: UUID) -> UUID:
    from armarius.infrastructure.daemon.models import WorkplaceModel
    from armarius.infrastructure.database.engine import get_sessionmaker

    async with get_sessionmaker()() as session:
        workplace = await session.get(WorkplaceModel, workplace_id)
    assert workplace is not None
    return workplace.machine_id


async def _hand_the_turn_to_a_machine(ws_id: str):
    """Treo lượt phỏng vấn lên kệ rồi xin nó về, qua đúng cửa daemon gọi.

    Trả về `(máy, lượt chạy, phần được giao)`. Đi qua cửa thật chứ không viết thẳng vào bảng,
    vì thứ đang canh chính là cửa ấy: gói việc được dựng ở đó, và trước T048a nó dựng hỏng.
    """
    from uuid import uuid4

    from armarius.infrastructure.daemon.enrollment import MachineIdentity
    from armarius.infrastructure.daemon.models import AgentWorkplaceBindingModel
    from armarius.infrastructure.database.engine import get_sessionmaker

    run = await _the_interview_run(ws_id)
    async with get_sessionmaker()() as session:
        binding = await session.get(AgentWorkplaceBindingModel, run.marius_id)
    assert binding is not None
    machine = MachineIdentity(
        machine_id=await _machine_of(binding.workplace_id),
        workspace_id=binding.workspace_id,
        owner_user_id=uuid4(),
        token_expires_at=None,
    )
    claims = app.state.container.daemon_claims
    await claims.offer(
        run_id=run.id,
        workspace_id=binding.workspace_id,
        workplace_id=binding.workplace_id,
    )
    granted = await claims.claim(
        machine, workplace_ids=[binding.workplace_id], free_slots=1
    )
    return machine, run, [g for g in granted if g.run_id == run.id]


async def _a_deferring_agent() -> None:
    """Một runtime **nhận** lượt rồi để đấy — hình dạng của một lượt giao cho máy."""
    _wire_agent([])
    app.state.container.registry._adapters["fake"].defer = True  # type: ignore[attr-defined]


async def test_the_machine_is_handed_the_interview_through_the_real_claim_door() -> None:
    """Cửa nhận việc thật, trên cơ sở dữ liệu thật, phải mặc áo được cho lượt phỏng vấn.

    Trước T048a nó **không** mặc được: gói việc dựng từ đầu việc, mà lượt này không có đầu
    việc nào, nên cửa trả ngay về kệ và thu hồi token nó vừa đúc.
    """
    async with await _client() as c:
        token, ws_id = await _register(c, "onbclaim@armarius.dev")
        h = {"Authorization": f"Bearer {token}"}
        await _online_wa(ws_id)
        await _a_deferring_agent()

        started = await c.post(f"/v1/workspaces/{ws_id}/onboarding", headers=h)
        assert started.status_code == 201, started.text
        sid = started.json()["id"]
        # Trả về trước khi agent kịp nói: lượt chạy còn nằm trên kệ.
        assert started.json()["collected"]["pending_question"] is None

        _machine, run, mine = await _hand_the_turn_to_a_machine(ws_id)

    assert run.task_id is None and run.project_id is None
    assert mine, "cửa nhận việc trả lượt phỏng vấn về kệ thay vì giao đi"
    assert "ARMARIUS · PROJECT ONBOARDING" in mine[0].prompt
    assert sid in mine[0].prompt
    assert mine[0].run_token  # và nó giữ token, thay vì bị thu hồi ngay sau khi đúc


async def test_a_turn_that_ends_silent_closes_the_chat_through_the_real_wiring() -> None:
    """Không ai đứng đợi câu trả lời nữa, nên cú khép lượt chạy phải là chỗ bắt cái hỏng.

    Đây là bài canh **dây nối** trong bộ dựng: cửa khép lượt chạy nói cho buổi phỏng vấn biết.
    Thiếu dây ấy thì lượt chạy vẫn khép đẹp, buổi phỏng vấn vẫn mở, và người chủ ngồi nhìn một
    khung chat không bao giờ nhúc nhích.
    """
    from armarius.domain.entities.run import RunStatus

    async with await _client() as c:
        token, ws_id = await _register(c, "onbsilent@armarius.dev")
        h = {"Authorization": f"Bearer {token}"}
        await _online_wa(ws_id)
        await _a_deferring_agent()

        sid = (await c.post(f"/v1/workspaces/{ws_id}/onboarding", headers=h)).json()["id"]
        machine, run, mine = await _hand_the_turn_to_a_machine(ws_id)
        assert mine

        # Máy chạy xong lượt ấy và không nói gì.
        await app.state.container.daemon_claims.finish(
            machine, run.id, status=RunStatus.COMPLETED
        )

        read = await c.get(f"/v1/onboarding/{sid}", headers=h)
    assert read.status_code == 200, read.text
    assert read.json()["status"] == "abandoned"


# ── một token còn sống không phải là một lượt còn được nói (review #253) ────────


async def test_the_previous_turn_cannot_write_after_the_chat_has_moved_on() -> None:
    """Token của lượt chạy sống tới lúc lượt ấy được khép, mà khép là **máy báo về** — nên có
    một quãng token cũ vẫn mở được cửa trong khi buổi phỏng vấn đã sang lượt khác.

    Kịch bản: agent hỏi bằng lượt 1, người chủ trả lời (xoá câu đang chờ, giao lượt 2), rồi
    lượt 1 gọi lại — gói tin trả lời rơi mất nên nó thử lại, hoặc nó chạy chậm. Câu ấy thuộc
    một bước đã qua. Cửa "một câu một lúc" không bắt được, vì xoá câu đang chờ đúng là việc
    trả lời làm.

    Đọc thành **404**, không phải 403: một lượt chạy với tay sang buổi không phải của nó không
    được biết buổi ấy có tồn tại hay không (Điều I).
    """
    async with await _client() as c:
        token, ws_id = await _register(c, "onbstale@armarius.dev")
        h = {"Authorization": f"Bearer {token}"}
        await _online_wa(ws_id)
        await _a_deferring_agent()

        sid = (await c.post(f"/v1/workspaces/{ws_id}/onboarding", headers=h)).json()["id"]
        _machine, _run, mine = await _hand_the_turn_to_a_machine(ws_id)
        assert mine
        first = {"Authorization": f"Bearer {mine[0].run_token}"}

        asked = await c.post(
            f"/agent/onboarding/{sid}/question",
            headers=first,
            json={
                "question": "What are you building?",
                "options": [{"id": "1", "label": "A web app"}],
                "multi": False,
            },
        )
        assert asked.status_code == 200, asked.text

        # Người chủ trả lời: câu đang chờ bị xoá, và lượt kế tiếp được giao cho một lượt chạy
        # mới. Token của lượt 1 **vẫn chưa bị thu hồi** — máy chưa báo lượt ấy xong.
        answered = await c.post(
            f"/v1/onboarding/{sid}/answer", headers=h, json={"answer": "A web app"}
        )
        assert answered.status_code == 200, answered.text

        stale = await c.post(
            f"/agent/onboarding/{sid}/question",
            headers=first,
            json={
                "question": "A question from the step before",
                "options": [{"id": "1", "label": "Anything"}],
                "multi": False,
            },
        )
        drafted = await c.post(
            f"/agent/onboarding/{sid}/complete",
            headers=first,
            json={
                "project": {"name": "Snuck In", "objective": "…"},
                "roster": [{"title": "Frontend", "description": "Builds the UI.", "seats": 1}],
            },
        )

        after = await c.get(f"/v1/onboarding/{sid}", headers=h)

    assert stale.status_code == 404, stale.text
    assert drafted.status_code == 404, drafted.text
    # Và buổi phỏng vấn không hề nhúc nhích: vẫn đang đợi lượt mới nói.
    collected = after.json()["collected"]
    assert collected["pending_question"] is None
    assert collected["draft"] is None
