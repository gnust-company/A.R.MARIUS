"""Duyệt một máy phải nói ra trên kênh không gian làm việc (FR-106, Hiến pháp IV).

*Người chủ tự đi hết luồng 2026-09-07*: đăng ký → ba bước → cài daemon → chạy `login` → daemon
tự mở trang phê duyệt trong **một cửa sổ khác** → duyệt ở đó → và cửa sổ đầu vẫn đứng nguyên ở
bước ba. Câu của họ: *"còn tab đang onboard bị mồ côi, tôi không biết phải dùng như nào nữa"*.

Cửa sổ đang đợi chỉ có hai đường để biết: hỏi vòng, thứ Điều IV cấm, hoặc được **đẩy tin sang**.
Bài này giữ đường thứ hai, và giữ ba điều dễ mất nhất ở nó:

  1. Duyệt xong thì có tin, trên đúng kênh của không gian làm việc ấy.
  2. Mã nối máy **không** đi theo tin. Nó là một giấy tờ còn sống cho tới lúc được đổi lấy token,
     và kênh này là thứ một browser mở suốt cả phiên.
  3. Người duyệt **trượt** không phát tin. Chỉ một người thắng lượt cập nhật có điều kiện, và chỉ
     người ấy mới được nói là đã nhận máy vào.
"""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from armarius.infrastructure.database.engine import init_db
from armarius.infrastructure.events.workspace_trace import EVENT_MACHINE_LINKED
from armarius.main import app

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


async def _a_machine_asking(c: AsyncClient) -> str:
    r = await c.post(
        "/daemon/link/start",
        json={
            "platform": "linux/amd64",
            "daemon_version": "0.1.0",
            "hostname": "gnust-thinkpad",
        },
    )
    assert r.status_code == 200, r.text
    return r.json()["code"]


def _heard(bus, workspace_id: str) -> list:
    return list(bus.backlog(f"ws:{workspace_id}"))


async def test_approving_a_machine_is_announced_on_that_workspace() -> None:
    async with _client() as c:
        headers, ws = await _patron(c, "link-announce@armarius.dev")
        code = await _a_machine_asking(c)
        bus = app.state.container.control_bus

        approved = await c.post(
            f"/v1/machines/link/{code}/approve", json={"workspace_id": ws}, headers=headers
        )
        assert approved.status_code == 200, approved.text

        linked = [e for e in _heard(bus, ws) if e.type == EVENT_MACHINE_LINKED]
        assert len(linked) == 1, [e.type for e in _heard(bus, ws)]
        assert linked[0].data == {"workspace_id": ws}, linked[0].data


async def test_the_link_code_never_rides_the_workspace_channel() -> None:
    """Mã còn sống cho tới khi được đổi lấy token, nên nó không được nằm trong tin đẩy."""
    async with _client() as c:
        headers, ws = await _patron(c, "link-nocode@armarius.dev")
        code = await _a_machine_asking(c)
        bus = app.state.container.control_bus

        await c.post(
            f"/v1/machines/link/{code}/approve", json={"workspace_id": ws}, headers=headers
        )

        for event in _heard(bus, ws):
            assert code not in repr(event.data), event.data


async def test_a_second_approver_announces_nothing() -> None:
    """Lượt duyệt thứ hai bị từ chối, nên nó không được nói là đã nhận máy vào."""
    async with _client() as c:
        headers, ws = await _patron(c, "link-twice@armarius.dev")
        code = await _a_machine_asking(c)
        bus = app.state.container.control_bus

        first = await c.post(
            f"/v1/machines/link/{code}/approve", json={"workspace_id": ws}, headers=headers
        )
        assert first.status_code == 200, first.text

        second = await c.post(
            f"/v1/machines/link/{code}/approve", json={"workspace_id": ws}, headers=headers
        )
        assert second.status_code == 409, second.text

        linked = [e for e in _heard(bus, ws) if e.type == EVENT_MACHINE_LINKED]
        assert len(linked) == 1, [e.data for e in linked]
