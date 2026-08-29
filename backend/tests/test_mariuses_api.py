"""Contract-conformance — adding an agent (API_CONTRACT §4.1, FR-007g).

Creating an agent takes a name and a workplace. Nothing is dialled out to and nothing is
pushed down: the machine the agent runs on asks for work rather than being called, so there
is no address to collect, nothing to probe, and no send to report.

What authenticates an agent is the token of the run it is in (FR-014g). The per-agent token
is still minted, because the two onboarding routes have nothing else to present until the
interview becomes a run of its own (FR-040c, T048a) — and the test below pins down that it
opens nothing else.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from armarius.infrastructure.database.engine import get_sessionmaker
from armarius.infrastructure.database.models import RunModel
from armarius.main import app
from tests.support.agents import (
    agent_token_for,
    invite_agent,
    ready_workplace,
)
from tests.support.runs import open_run


async def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def _register(c: AsyncClient, email: str) -> tuple[str, str]:
    r = await c.post(
        "/auth/register",
        json={"email": email, "full_name": "Patron", "password": "password1234"},
    )
    assert r.status_code == 201, r.text
    token = r.json()["tokens"]["access_token"]
    ws = await c.get("/v1/workspaces", headers={"Authorization": f"Bearer {token}"})
    return token, ws.json()[0]["id"]


async def test_creating_an_agent_never_returns_its_token_and_reports_no_send() -> None:
    async with await _client() as c:
        token, ws_id = await _register(c, "inv@armarius.dev")
        h = {"Authorization": f"Bearer {token}"}
        data = await invite_agent(c, ws_id, h)

    assert data["invite_status"] == "approved"  # there is no approval step to wait for
    # The token is a secret — it must not leak through the API.
    assert "agent_token" not in data
    assert "invite" not in data
    # And there is no send to report on: nothing was dialled out to, nothing was pushed
    # down. A field saying otherwise would be describing an act that no longer happens.
    assert "send_status" not in data


async def test_agent_me_authenticates_with_the_token_of_a_live_run() -> None:
    """Token của lượt chạy mở `/agent/me`, và cú gọi ấy tính là một lần chạm (FR-014g)."""
    async with await _client() as c:
        token, ws_id = await _register(c, "online@armarius.dev")
        h = {"Authorization": f"Bearer {token}"}
        data = await invite_agent(c, ws_id, h)
        run = await open_run(marius_id=data["id"])

        me = await c.get("/agent/me", headers=run.headers)
    assert me.status_code == 200, me.text
    assert me.json()["marius"]["liveness"] == "online"


async def test_the_long_lived_agent_token_no_longer_opens_anything() -> None:
    """Loại token thứ ba đã hết việc — và "hết việc" phải *có tác dụng*, không chỉ là một
    câu trong đặc tả.

    Nó vẫn được đúc, vì hai lối onboarding chưa có gì để trình (FR-040c, T048a). Bài này canh
    đúng chỗ nguy hiểm: một token còn nằm trong bảng mà vẫn mở được cửa thì FR-014g mới chỉ đúng
    trên giấy. Đọc thành **404**, không phải 403 — không-phải-của-bạn và không-tồn-tại đọc y hệt
    nhau (Điều I), nên ai cầm một chuỗi đã chết cũng không xác nhận được nó từng mở thứ gì.
    """
    async with await _client() as c:
        token, ws_id = await _register(c, "deadtoken@armarius.dev")
        h = {"Authorization": f"Bearer {token}"}
        data = await invite_agent(c, ws_id, h)
        stale = await agent_token_for(data["id"])

        me = await c.get("/agent/me", headers={"Authorization": f"Bearer {stale}"})
    assert me.status_code == 404, me.text
    assert me.json()["code"] == "run_not_found"


async def test_the_caller_does_not_get_to_choose_a_runtime() -> None:
    """Which tool runs an agent follows from where it works, not from the request body.

    A runtime named on the wire is a runtime nothing on this machine may be able to run, and
    an agent created around one is an agent that can never take a turn. The field is not
    refused with an error — it is simply not a thing this route accepts.
    """
    async with await _client() as c:
        token, ws_id = await _register(c, "noadapter@armarius.dev")
        h = {"Authorization": f"Bearer {token}"}
        r = await c.post(
            f"/v1/workspaces/{ws_id}/mariuses",
            headers=h,
            json={
                "name": "Nobody",
                "adapter_type": "no-such-runtime",
                "workplace_id": await ready_workplace(ws_id),
            },
        )
    assert r.status_code == 201, r.text
    assert r.json()["adapter_type"] != "no-such-runtime"


async def test_two_agents_in_one_workspace_cannot_share_a_name() -> None:
    async with await _client() as c:
        token, ws_id = await _register(c, "twins@armarius.dev")
        h = {"Authorization": f"Bearer {token}"}
        await invite_agent(c, ws_id, h, name="Marin")

        clash = await c.post(
            f"/v1/workspaces/{ws_id}/mariuses",
            headers=h,
            json={"name": "Marin", "workplace_id": await ready_workplace(ws_id)},
        )
    # 409, not 422: the request is perfectly well formed, the world is what refuses it.
    assert clash.status_code == 409, clash.text
    assert clash.json()["code"] == "agent_name_taken"


async def _seed_run(marius_id: str, *, created_at: datetime, status: str = "completed") -> UUID:
    """Persist one run for an agent the way the wake engine would (plain-UUID ref)."""
    run_id = uuid4()
    async with get_sessionmaker()() as s:
        s.add(
            RunModel(
                id=run_id,
                marius_id=UUID(marius_id),
                task_id=uuid4(),
                adapter_type="echo",
                wake_source="assignment",
                status=status,
                created_at=created_at,
            )
        )
        await s.commit()
    return run_id


async def test_list_marius_runs_returns_agent_runs_newest_first() -> None:
    """The agent-detail feed reads the agent's runs, newest first, scoped to that agent."""
    async with await _client() as c:
        token, ws_id = await _register(c, "runs@armarius.dev")
        h = {"Authorization": f"Bearer {token}"}
        agent = await invite_agent(c, ws_id, h, name="Runner")
        other = await invite_agent(c, ws_id, h, name="Bystander")

        older = await _seed_run(
            agent["id"], created_at=datetime(2026, 7, 1, tzinfo=UTC)
        )
        newer = await _seed_run(
            agent["id"], created_at=datetime(2026, 7, 5, tzinfo=UTC)
        )
        # A run for a different agent must NOT leak into this agent's feed.
        await _seed_run(other["id"], created_at=datetime(2026, 7, 9, tzinfo=UTC))

        r = await c.get(f"/v1/workspaces/{ws_id}/mariuses/{agent['id']}/runs", headers=h)

    assert r.status_code == 200, r.text
    runs = r.json()
    assert [run["id"] for run in runs] == [str(newer), str(older)]  # newest first
    assert runs[0]["marius_id"] == agent["id"]
    assert runs[0]["wake_source"] == "assignment"
    assert runs[0]["status"] == "completed"


async def test_list_marius_runs_is_empty_for_a_fresh_agent() -> None:
    async with await _client() as c:
        token, ws_id = await _register(c, "freshruns@armarius.dev")
        h = {"Authorization": f"Bearer {token}"}
        agent = await invite_agent(c, ws_id, h)
        r = await c.get(f"/v1/workspaces/{ws_id}/mariuses/{agent['id']}/runs", headers=h)
    assert r.status_code == 200, r.text
    assert r.json() == []


async def test_list_marius_runs_cross_workspace_is_404() -> None:
    """An agent that lives in another workspace 404s — no cross-tenant run leakage."""
    async with await _client() as c:
        token_a, ws_a = await _register(c, "runs-a@armarius.dev")
        token_b, ws_b = await _register(c, "runs-b@armarius.dev")
        ha = {"Authorization": f"Bearer {token_a}"}
        hb = {"Authorization": f"Bearer {token_b}"}
        agent_a = await invite_agent(c, ws_a, ha, name="AOnly")
        # B asks for A's agent under B's own workspace → agent not in this workspace → 404.
        r = await c.get(
            f"/v1/workspaces/{ws_b}/mariuses/{agent_a['id']}/runs", headers=hb
        )
    assert r.status_code == 404, r.text


@pytest.mark.parametrize("missing", ["marius", "workspace"])
async def test_cross_workspace_invite_is_404(missing: str) -> None:
    async with await _client() as c:
        token_a, ws_a = await _register(c, f"a-{missing}@armarius.dev")
        token_b, ws_b = await _register(c, f"b-{missing}@armarius.dev")
        hb = {"Authorization": f"Bearer {token_b}"}
        # User B may not invite into User A's workspace.
        r = await c.post(
            f"/v1/workspaces/{ws_a}/mariuses",
            headers=hb,
            json={
                "name": "X",
                "adapter_type": "echo",
                "workplace_id": await ready_workplace(ws_a),
            },
        )
    assert r.status_code == 404, r.text
