"""Nhật ký của một lượt chạy không thuộc đầu việc nào phải mở được (FR-016, FR-040c).

*Người chủ báo 2026-09-07: "có khá nhiều activity onboarding_answered nhưng lại không có trace
nào được record, ấn open full log không thấy gì".* Sự kiện **có** được ghi — sáu cái mỗi lượt,
21/21 lượt trong cơ sở dữ liệu đều có. Thứ hỏng là cái cổng: `own_run` từ chối mọi lượt chạy
không có `task_id`, mà buổi dựng đội và mỗi lượt nói chuyện với Trưởng dự án **cố ý** không có
(FR-040c). Nên màn hình liệt kê ra những lượt ấy, còn mọi cửa mở nhật ký của chúng đều trả lời
*không có lượt chạy nào như thế*.

Bài ở đây đi qua cửa HTTP thật vì câu hỏi là *mở được hay không*, và câu ấy chỉ đúng ở đầu HTTP.
"""

from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from armarius.domain.entities.run import Run, RunEvent, RunStatus
from armarius.infrastructure.database.engine import init_db
from armarius.main import app
from tests.support.agents import invite_agent, ready_workplace
from tests.support.machines import auth


@pytest.fixture(autouse=True)
async def _bootstrap():
    await init_db()
    yield


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def _patron(c: AsyncClient, email: str) -> tuple[dict[str, str], str]:
    r = await c.post(
        "/auth/register",
        json={"email": email, "full_name": "Patron", "password": "password1234"},
    )
    assert r.status_code == 201, r.text
    headers = auth(r.json()["tokens"]["access_token"])
    workspaces = await c.get("/v1/workspaces", headers=headers)
    return headers, workspaces.json()[0]["id"]


async def _an_interview_run(marius_id: str, events: int = 3) -> str:
    """Đúng hình dạng buổi dựng đội mở ra: không đầu việc, không dự án, có sự kiện."""
    container = app.state.container
    async with container.uow_factory() as uow:
        run = await uow.runs.add(
            Run(
                marius_id=UUID(marius_id),
                adapter_type="echo",
                status=RunStatus.COMPLETED,
            )
        )
        for seq in range(1, events + 1):
            await uow.run_events.add(
                RunEvent(run_id=run.id, seq=seq, type="assistant.message", payload={"n": seq})
            )
        await uow.commit()
        return str(run.id)


async def test_the_log_of_a_run_about_no_task_opens() -> None:
    async with _client() as c:
        headers, ws = await _patron(c, "interview-log@armarius.dev")
        workplace = await ready_workplace(ws)
        agent = await invite_agent(c, ws, headers, name="Gnust", workplace_id=workplace)
        run_id = await _an_interview_run(agent["id"])

        # Màn agent liệt kê nó ra — đó là chỗ người chủ nhìn thấy `onboarding_answered`.
        listed = await c.get(
            f"/v1/workspaces/{ws}/mariuses/{agent['id']}/runs", headers=headers
        )
        assert listed.status_code == 200, listed.text
        assert run_id in [r["id"] for r in listed.json()], listed.json()

        # Và mọi cửa mở nhật ký của nó cũng phải mở được. Liệt kê ra một hàng rồi từ chối mọi
        # đường vào nó là chỗ hỏng người chủ gặp.
        one = await c.get(f"/v1/runs/{run_id}", headers=headers)
        assert one.status_code == 200, one.text

        events = await c.get(f"/v1/runs/{run_id}/events", headers=headers)
        assert events.status_code == 200, events.text
        assert [e["seq"] for e in events.json()] == [1, 2, 3], events.json()


async def test_a_run_about_no_task_is_still_nobody_elses_to_read() -> None:
    """Nới cổng ra cho đúng chủ **không** được nới cho người ngoài (Hiến pháp I)."""
    async with _client() as c:
        mine, ws = await _patron(c, "interview-mine@armarius.dev")
        workplace = await ready_workplace(ws)
        agent = await invite_agent(c, ws, mine, name="Gnust", workplace_id=workplace)
        run_id = await _an_interview_run(agent["id"])

        stranger, _ = await _patron(c, "interview-stranger@armarius.dev")

        for path in (f"/v1/runs/{run_id}", f"/v1/runs/{run_id}/events"):
            refused = await c.get(path, headers=stranger)
            # 404, không phải 403: nói *cấm* là xác nhận hàng ấy có thật, mà đó là một sự thật
            # thuộc về người khác.
            assert refused.status_code == 404, f"{path} → {refused.status_code}"
            assert refused.json()["code"] == "run_not_found", refused.json()


async def test_a_run_id_nobody_issued_still_reads_as_not_there() -> None:
    async with _client() as c:
        headers, _ws = await _patron(c, "interview-nosuch@armarius.dev")
        missing = await c.get(f"/v1/runs/{uuid4()}/events", headers=headers)
        assert missing.status_code == 404, missing.text
