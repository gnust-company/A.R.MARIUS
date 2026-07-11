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

    The WA is never lazy-created anymore — we create + activate an agent directly and seat it
    as host (the unit-style bypass of the HTTP invite path), so onboarding's wake finds a
    ready host whose adapter_type the wired FakeAdapter will satisfy.
    """
    from armarius.domain.entities.marius import InviteStatus, Marius

    ws_uuid = UUID(ws_id)
    async with make_uow() as uow:
        host = Marius(
            workspace_id=ws_uuid,
            name="Workspace Agent",
            role="Workspace Agent",
            adapter_type="hermes_gateway",
            liveness=Liveness.ONLINE,
            invite_status=InviteStatus.APPROVED,
            agent_token="arm_wa",
        )
        await uow.mariuses.add(host)
        ws = await uow.workspaces.get(ws_uuid)
        assert ws is not None
        ws.workspace_agent_id = host.id
        await uow.workspaces.update(ws)
        await uow.commit()


def _wire_agent(drivers: list) -> FakeAdapter:
    """Swap the app's hermes_gateway adapter for a fake that scripts the WA's turns."""
    fake = FakeAdapter(drivers=drivers)
    app.state.container.registry._adapters["hermes_gateway"] = fake  # type: ignore[attr-defined]
    return fake


def _ask(container, key: str, question: str):
    async def driver(session_id) -> None:
        await container.onboarding.agent_post_question(
            session_id,
            {"key": key, "question": question,
             "options": [{"id": "1", "label": "A web app"}, {"id": "other", "label": "Other"}],
             "multi": False},
        )

    return driver


def _complete(container, name: str, objective: str):
    async def driver(session_id) -> None:
        await container.onboarding.agent_post_complete(
            session_id,
            {"name": name, "objective": objective, "success_metrics": None,
             "target_date": None, "context": None,
             "roster": [
                 {"key": "leader", "title": "Project Leader", "seats": 1, "is_leader": True},
                 {"key": "frontend", "title": "Frontend", "seats": 1, "is_leader": False},
             ]},
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
