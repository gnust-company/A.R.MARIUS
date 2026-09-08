"""Một dự án khai **cần bao nhiêu người**, và khai được từ cả hai đường vào (FR-007n).

*Người chủ hỏi 2026-09-07: "tại sao khi tạo dự án bằng workspace agent xong thì mặc định dự án
chỉ có 1 PL và 1 Worker đợi grant vậy?"* — rồi 2026-09-08 chốt: bước tạo dự án phải có chỗ khai
**số worker**, thay cho việc dựng vai rồi khai số ghế cho vai ấy.

Băng ghế trước đây sinh ra với đúng một chỗ, nên một dự án sáu người đọc trên màn hình thành một
dự án chỉ được một người — và không đường nào sửa được con số ấy. Con số này **không phải một
vai**: nó nói dự án *lớn cỡ nào*, còn *ai làm* là người chủ chọn và *làm gì* thì đã viết trên
chính agent (FR-007l vẫn nguyên).

Ba điều được giữ ở đây, và điều thứ ba là điều đáng nhất:

  1. Khai bao nhiêu thì hiện ra bấy nhiêu chỗ.
  2. Con số là **sàn, không phải trần** — ngồi quá số đã khai vẫn được, và số đọc ra lớn theo.
  3. **Không có agent nào cũng tạo được dự án.** Đây là chỗ luồng cũ chặn người dùng: một tài
     khoản mới bỏ qua bước nối máy thì chưa có agent thật nào, mà màn tạo dự án lại đòi ít nhất
     một người — nên hoặc không tạo được gì, hoặc phải đem chính Tác nhân Không gian ra làm thợ.
"""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from armarius.application.use_cases.onboarding_session import _worker_count
from armarius.application.use_cases.projects import MAX_WORKER_COUNT
from armarius.infrastructure.database.engine import init_db
from armarius.main import app
from tests.support.agents import invite_agent, ready_workplace

pytestmark = pytest.mark.anyio


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
    headers = {"Authorization": f"Bearer {r.json()['tokens']['access_token']}"}
    ws = await c.get("/v1/workspaces", headers=headers)
    return headers, ws.json()[0]["id"]


def _bench(detail: dict) -> dict:
    return next(row for row in detail["roster"] if not row["is_leader"])


async def _create(
    c: AsyncClient, ws: str, headers: dict[str, str], **body
) -> dict:
    payload = {
        "name": body.pop("name", "Apollo"),
        "objective": "Ship the thing",
        "leader": {"description": "Owns the plan and coordinates the team."},
        **body,
    }
    r = await c.post(f"/v1/workspaces/{ws}/projects", json=payload, headers=headers)
    assert r.status_code == 201, r.text
    return r.json()


async def test_a_project_shows_as_many_worker_places_as_it_asked_for() -> None:
    async with _client() as c:
        headers, ws = await _patron(c, "worker-count@armarius.dev")
        detail = await _create(c, ws, headers, worker_count=4)

        bench = _bench(detail)
        assert bench["seats"] == 4, bench
        assert bench["filled"] == 0, bench
        assert bench["seated"] == [], bench


async def test_not_saying_how_many_still_means_one() -> None:
    """Cửa cũ không gửi con số, và nó phải tiếp tục chạy y như trước."""
    async with _client() as c:
        headers, ws = await _patron(c, "worker-default@armarius.dev")
        detail = await _create(c, ws, headers)
        assert _bench(detail)["seats"] == 1, _bench(detail)


async def test_the_number_is_a_floor_not_a_cap() -> None:
    """Khai hai mà ngồi ba thì đọc ra ba — không ai bị chặn bởi một con số."""
    async with _client() as c:
        headers, ws = await _patron(c, "worker-floor@armarius.dev")
        workplace = await ready_workplace(ws)
        agents = [
            await invite_agent(c, ws, headers, name=name, workplace_id=workplace)
            for name in ("Alice", "Bob", "Cleo")
        ]
        project = await _create(c, ws, headers, worker_count=2)

        for agent in agents:
            seated = await c.post(
                f"/v1/projects/{project['id']}/members",
                json={"marius_id": agent["id"]},
                headers=headers,
            )
            assert seated.status_code in (200, 201), seated.text

        detail = await c.get(f"/v1/projects/{project['id']}", headers=headers)
        bench = _bench(detail.json())
        assert bench["filled"] == 3, bench
        assert bench["seats"] == 3, bench


async def test_a_workspace_with_no_agents_can_still_create_a_project() -> None:
    """Chỗ luồng cũ chặn người dùng: chưa có agent thì vẫn phải tạo được dự án."""
    async with _client() as c:
        headers, ws = await _patron(c, "worker-empty@armarius.dev")
        detail = await _create(c, ws, headers, worker_count=3, members=[])

        assert detail["status"] == "setup", detail["status"]
        bench = _bench(detail)
        assert (bench["seats"], bench["filled"]) == (3, 0), bench
        leader = next(row for row in detail["roster"] if row["is_leader"])
        assert leader["filled"] == 0, leader


async def test_the_number_can_be_changed_afterwards() -> None:
    async with _client() as c:
        headers, ws = await _patron(c, "worker-edit@armarius.dev")
        project = await _create(c, ws, headers, worker_count=2)

        raised = await c.patch(
            f"/v1/projects/{project['id']}", json={"worker_count": 6}, headers=headers
        )
        assert raised.status_code == 200, raised.text
        assert _bench(raised.json())["seats"] == 6, _bench(raised.json())

        lowered = await c.patch(
            f"/v1/projects/{project['id']}", json={"worker_count": 1}, headers=headers
        )
        assert lowered.status_code == 200, lowered.text
        assert _bench(lowered.json())["seats"] == 1, _bench(lowered.json())


async def test_lowering_the_number_never_unseats_anybody() -> None:
    async with _client() as c:
        headers, ws = await _patron(c, "worker-lower@armarius.dev")
        workplace = await ready_workplace(ws)
        agent = await invite_agent(c, ws, headers, name="Alice", workplace_id=workplace)
        project = await _create(c, ws, headers, worker_count=5)
        await c.post(
            f"/v1/projects/{project['id']}/members",
            json={"marius_id": agent["id"]},
            headers=headers,
        )

        await c.patch(
            f"/v1/projects/{project['id']}", json={"worker_count": 1}, headers=headers
        )
        detail = await c.get(f"/v1/projects/{project['id']}", headers=headers)
        bench = _bench(detail.json())
        assert bench["filled"] == 1, bench
        assert len(bench["seated"]) == 1, bench


async def test_a_refused_number_is_refused_at_the_door() -> None:
    """Số ngoài biên bị từ chối kèm câu đọc được, không bị lặng lẽ kẹp lại."""
    async with _client() as c:
        headers, ws = await _patron(c, "worker-bounds@armarius.dev")
        for bad in (0, -3, MAX_WORKER_COUNT + 1):
            r = await c.post(
                f"/v1/workspaces/{ws}/projects",
                json={
                    "name": f"Apollo {bad}",
                    "objective": "Ship the thing",
                    "leader": {"description": "Owns the plan."},
                    "worker_count": bad,
                },
                headers=headers,
            )
            assert r.status_code == 422, f"{bad} → {r.status_code}"


def test_a_how_many_answer_is_read_loosely_and_never_refused() -> None:
    """Agent trả lời *bao nhiêu* bằng nhiều dạng, và không dạng nào đáng bỏ cả buổi phỏng vấn."""
    assert _worker_count(3) == 3
    assert _worker_count("3") == 3
    assert _worker_count("3 người") == 3
    assert _worker_count("around 4 people") == 4
    # Không đọc được thì về một — đúng con số mọi dự án vẫn có trước khi có câu hỏi này.
    assert _worker_count(None) == 1
    assert _worker_count("three") == 1
    assert _worker_count("") == 1
    assert _worker_count({"n": 3}) == 1
    # `True` là int trong Python, và một dự án "cần True người" thì vô nghĩa.
    assert _worker_count(True) == 1
    # Biên vẫn được giữ ở đây, vì con số này đi thẳng vào băng ghế.
    assert _worker_count(0) == 1
    assert _worker_count(9999) == MAX_WORKER_COUNT
