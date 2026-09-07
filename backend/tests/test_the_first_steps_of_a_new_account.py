"""Ba bước đầu tiên của một tài khoản, và người chủ nhà của không gian làm việc.

Đặc tả: `specs/003-onboarding-tai-khoan-moi/spec.md` — FR-100, FR-101, FR-104, FR-110, FR-111,
FR-112.

Bài ở đây đi qua **cửa thật**, không gọi use case: câu hỏi là *một người mới đăng ký thì nhận
được gì*, và câu trả lời chỉ đúng nếu nó đúng ở đầu HTTP.
"""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from armarius.application.use_cases.workspace_agent import HOST_NAME
from armarius.infrastructure.database.engine import init_db
from armarius.main import app
from tests.support.machines import auth, link_machine


@pytest.fixture(autouse=True)
async def _bootstrap():
    await init_db()
    yield


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def _register(c: AsyncClient, email: str) -> tuple[dict[str, str], str]:
    r = await c.post(
        "/auth/register",
        json={"email": email, "full_name": "Vũ", "password": "password1234"},
    )
    assert r.status_code == 201, r.text
    headers = auth(r.json()["tokens"]["access_token"])
    workspaces = await c.get("/v1/workspaces", headers=headers)
    return headers, workspaces.json()[0]["id"]


# ── ba bước (FR-100, FR-104) ──────────────────────────────────────────────────


async def test_somebody_who_just_registered_has_not_been_through_the_first_steps() -> None:
    """Câu này là thứ ứng dụng hỏi trước khi quyết định hiện màn nào (FR-104)."""
    async with _client() as c:
        headers, _ws = await _register(c, "first-steps@armarius.dev")

        me = (await c.get("/auth/me", headers=headers)).json()
        assert me["onboarded"] is False
        assert me["onboarding_step"] == 0


async def test_the_display_name_can_be_changed_by_the_person_it_belongs_to() -> None:
    """FR-101. Trước đây không có cửa nào: tên nhập lúc đăng ký là tên vĩnh viễn."""
    async with _client() as c:
        headers, _ws = await _register(c, "rename-self@armarius.dev")

        changed = await c.patch("/auth/me", headers=headers, json={"full_name": "Vũ Nguyễn"})
        assert changed.status_code == 200, changed.text
        assert changed.json()["full_name"] == "Vũ Nguyễn"
        # Và nó ở lại — đây là hàng dữ liệu, không phải một câu trả lời.
        assert (await c.get("/auth/me", headers=headers)).json()["full_name"] == "Vũ Nguyễn"


async def test_only_what_was_sent_is_touched() -> None:
    """Lưu một ô không được xoá ô khác vừa được sửa ở một tab thứ hai."""
    async with _client() as c:
        headers, _ws = await _register(c, "partial-save@armarius.dev")
        await c.patch("/auth/me", headers=headers, json={"full_name": "Vũ Nguyễn"})

        stepped = await c.patch("/auth/me", headers=headers, json={"onboarding_step": 2})
        assert stepped.status_code == 200, stepped.text
        assert stepped.json()["onboarding_step"] == 2
        assert stepped.json()["full_name"] == "Vũ Nguyễn"


async def test_finishing_the_first_steps_is_remembered_and_is_one_way() -> None:
    """FR-104: đi xong rồi thì lần sau đăng nhập không gặp lại.

    Và không có đường quay lại: không có lý do sản phẩm nào để đẩy một người trở vào luồng dành
    cho người mới, nên một cửa làm được việc ấy chỉ có thể làm nó do vô tình.
    """
    async with _client() as c:
        headers, _ws = await _register(c, "finish-steps@armarius.dev")

        done = await c.patch(
            "/auth/me", headers=headers, json={"onboarding_step": 3, "onboarding_done": True}
        )
        assert done.status_code == 200, done.text
        assert done.json()["onboarded"] is True

        undo = await c.patch("/auth/me", headers=headers, json={"onboarding_done": False})
        assert undo.status_code == 200, undo.text
        assert undo.json()["onboarded"] is True, "xong rồi thì không có đường quay lại"

        # Sang một phiên đăng nhập khác thì vẫn xong.
        again = await c.post(
            "/auth/login",
            json={"email": "finish-steps@armarius.dev", "password": "password1234"},
        )
        fresh = auth(again.json()["tokens"]["access_token"])
        assert (await c.get("/auth/me", headers=fresh)).json()["onboarded"] is True


async def test_a_step_outside_the_three_is_refused() -> None:
    async with _client() as c:
        headers, _ws = await _register(c, "bad-step@armarius.dev")

        assert (
            await c.patch("/auth/me", headers=headers, json={"onboarding_step": 9})
        ).status_code == 422
        assert (
            await c.patch("/auth/me", headers=headers, json={"full_name": ""})
        ).status_code == 422


async def test_nobody_can_rename_somebody_else() -> None:
    async with _client() as c:
        await _register(c, "victim@armarius.dev")
        stranger, _ws = await _register(c, "stranger@armarius.dev")

        # Không có đường nào nhận id của người khác cả — cửa này chỉ nói về chính người gọi.
        changed = await c.patch("/auth/me", headers=stranger, json={"full_name": "Nobody"})
        assert changed.json()["email"] == "stranger@armarius.dev"
        assert (
            await c.post(
                "/auth/login", json={"email": "victim@armarius.dev", "password": "password1234"}
            )
        ).status_code == 200


async def test_the_first_steps_belong_to_a_person_not_to_a_door() -> None:
    """Không có token thì không đọc và không sửa được gì."""
    async with _client() as c:
        assert (await c.get("/auth/me")).status_code in (401, 403)
        assert (await c.patch("/auth/me", json={"full_name": "X"})).status_code in (401, 403)


# ── người chủ nhà (FR-110, FR-111, FR-112) ────────────────────────────────────


async def test_a_new_account_gets_a_workspace_with_a_host_already_in_it() -> None:
    """FR-110 + FR-111: có mặt, giữ ghế, ngoại tuyến với lý do đọc được."""
    async with _client() as c:
        headers, ws = await _register(c, "has-host@armarius.dev")

        directory = (await c.get(f"/v1/workspaces/{ws}/mariuses", headers=headers)).json()
        hosts = [m for m in directory if m["role"] == "Workspace Agent"]
        assert len(hosts) == 1, directory
        host = hosts[0]
        assert host["name"] == HOST_NAME
        assert host["liveness"] == "offline"
        # Chưa nối máy nào, nên lý do là *chưa được đặt vào runtime nào* — một mã, không phải
        # một câu, vì hai người đọc nó bằng hai ngôn ngữ (Hiến pháp Điều VII).
        assert host["offline_reason"] == "not_placed", host


async def test_a_workspace_made_by_hand_gets_one_too() -> None:
    """FR-110 nói **mọi** không gian làm việc, không riêng cái tạo lúc đăng ký."""
    async with _client() as c:
        headers, _ws = await _register(c, "second-workspace@armarius.dev")

        made = await c.post("/v1/workspaces", headers=headers, json={"name": "Xưởng hai"})
        assert made.status_code == 201, made.text
        second = made.json()["id"]

        directory = (await c.get(f"/v1/workspaces/{second}/mariuses", headers=headers)).json()
        assert [m["name"] for m in directory] == [HOST_NAME], directory


async def test_linking_the_first_machine_puts_the_host_to_work() -> None:
    """FR-112, qua đúng luồng thật: máy xin vào, người duyệt, máy khai runtime nó chạy được."""
    async with _client() as c:
        machine = await link_machine(c, "host-goes-to-work@armarius.dev")

        directory = (
            await c.get(f"/v1/workspaces/{machine.workspace_id}/mariuses", headers=machine.headers)
        ).json()
        host = next(m for m in directory if m["role"] == "Workspace Agent")
        # Đã có chỗ làm việc, nên không còn lý do ngoại tuyến nào của việc *chưa được đặt chỗ*.
        assert host["offline_reason"] is None, host

        # Và màn Máy kể ra nó đang ở đâu.
        machines = (
            await c.get(f"/v1/workspaces/{machine.workspace_id}/machines", headers=machine.headers)
        ).json()
        living = [a["name"] for a in machines[0]["workplaces"][0]["agents"]]
        assert living == [HOST_NAME], living


async def test_a_machine_reporting_nothing_it_can_run_leaves_the_host_where_it_was() -> None:
    """Máy khai một runtime **không nhận việc được** thì không phải một chỗ để đặt ai vào."""
    async with _client() as c:
        machine = await link_machine(c, "nothing-ready@armarius.dev")
        # Máy nói nó đang tắt: mọi runtime của nó đóng lại.
        stopping = await c.put(
            "/daemon/workplaces",
            headers=auth(machine.token),
            json={"workplaces": [], "symlink_capable": True, "stopping": True},
        )
        assert stopping.status_code == 200, stopping.text

        directory = (
            await c.get(f"/v1/workspaces/{machine.workspace_id}/mariuses", headers=machine.headers)
        ).json()
        host = next(m for m in directory if m["role"] == "Workspace Agent")
        assert host["liveness"] == "offline", host
