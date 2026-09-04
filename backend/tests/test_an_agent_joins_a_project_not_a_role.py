"""Thêm agent vào dự án là thêm **agent**, không phải dựng thêm một vai (T039j, FR-007l).

Đường cũ đi hai bước: người chủ tạo một vai — tên vai, số ghế, mô tả công việc — rồi mới cấp
ghế ấy cho một agent. Nghĩa là họ phải viết tay bản mô tả *cách cư xử* thứ hai, đặt cạnh
instructions vốn đã ghi trên chính con agent, và hai bản ấy lệch nhau theo thời gian.

Bốn thứ đo ở đây:

1. **Bảng nhân sự của dự án không phình ra** dù có bao nhiêu agent vào — vẫn đúng hai dòng, và
   không dòng nào do ai đặt ra.
2. **Không còn cửa nào dựng được vai.** Đo bằng sự vắng mặt, vì đó là cách duy nhất đo được
   một luật kiểu này.
3. **Gói tin agent nhận được không còn mô tả công việc do người chủ gõ.** Chỗ nó ngồi chỉ
   trỏ về instructions của chính nó — nếu vai còn sống thì câu chữ của vai sẽ nằm trong gói tin.
4. **Chỗ ngồi chung không có trần**, còn ghế Trưởng dự án thì có đúng một chỗ.

Ghi 2026-09-04: một bản kế hoạch còn mang `roles` bị **từ chối**, không phải bị lặng lẽ bỏ qua
— cửa tạo dự án sẽ trả 201 với một dự án trống người, và người chủ nhìn vào đó không hiểu bước
nào của mình hỏng. Đúng cái bẫy tham số chết đã cắn ở T048c.
"""

from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from armarius.application.use_cases.projects import (
    LEADER_ROLE_KEY,
    MEMBERS_ROLE_DESCRIPTION,
    MEMBERS_ROLE_KEY,
)
from armarius.main import app
from tests.support.agents import invite_agent, invite_and_online
from tests.support.projects import force_operating
from tests.support.runs import open_run

pytestmark = pytest.mark.asyncio


async def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def _register(c: AsyncClient, email: str) -> tuple[dict, str]:
    r = await c.post(
        "/auth/register",
        json={"email": email, "full_name": "Patron", "password": "password1234"},
    )
    assert r.status_code == 201, r.text
    h = {"Authorization": f"Bearer {r.json()['tokens']['access_token']}"}
    ws = await c.get("/v1/workspaces", headers=h)
    return h, ws.json()[0]["id"]


async def _project(c: AsyncClient, ws_id: str, h: dict, **body) -> dict:
    r = await c.post(
        f"/v1/workspaces/{ws_id}/projects",
        headers=h,
        json={
            "name": f"Apollo-{uuid4().hex[:4]}",
            "objective": "Ra mắt nền tảng",
            "leader": {"description": "Điều phối dự án.", "marius_id": None},
            **body,
        },
    )
    assert r.status_code == 201, r.text
    return r.json()


# ── 1. bảng nhân sự không phình ra ────────────────────────────────────────────


async def test_a_project_has_the_same_two_rows_however_many_agents_join() -> None:
    async with await _client() as c:
        h, ws_id = await _register(c, "join1@armarius.dev")
        pid = (await _project(c, ws_id, h))["id"]

        for i in range(4):
            mid, _ = await invite_and_online(c, ws_id, h, name=f"Người-{i}")
            joined = await c.post(
                f"/v1/projects/{pid}/members", headers=h, json={"marius_id": mid}
            )
            assert joined.status_code == 201, joined.text

        roster = (await c.get(f"/v1/projects/{pid}/roster", headers=h)).json()
        agents = (await c.get(f"/v1/projects/{pid}/agents", headers=h)).json()

    assert {r["key"] for r in roster} == {LEADER_ROLE_KEY, MEMBERS_ROLE_KEY}
    assert len(agents) == 4
    # Và chỗ ngồi chung khai đúng số người đang ngồi, chứ không khai con số đã lưu.
    bench = next(r for r in roster if r["key"] == MEMBERS_ROLE_KEY)
    assert (bench["seats"], bench["filled"]) == (4, 4)


async def test_the_agents_named_when_the_project_is_created_are_already_on_it() -> None:
    async with await _client() as c:
        h, ws_id = await _register(c, "join2@armarius.dev")
        lead, _ = await invite_and_online(c, ws_id, h, name="Trưởng")
        one, _ = await invite_and_online(c, ws_id, h, name="Một")
        two, _ = await invite_and_online(c, ws_id, h, name="Hai")

        made = await _project(
            c, ws_id, h,
            leader={"description": "Điều phối dự án.", "marius_id": lead},
            members=[one, two],
        )
        agents = (await c.get(f"/v1/projects/{made['id']}/agents", headers=h)).json()
        roster = (await c.get(f"/v1/projects/{made['id']}/roster", headers=h)).json()

    assert {a["marius_id"] for a in agents} == {lead, one, two}
    assert {r["key"] for r in roster} == {LEADER_ROLE_KEY, MEMBERS_ROLE_KEY}


# ── 2. không còn cửa nào dựng được vai ────────────────────────────────────────


async def test_a_plan_that_still_carries_roles_is_refused() -> None:
    async with await _client() as c:
        h, ws_id = await _register(c, "join3@armarius.dev")
        r = await c.post(
            f"/v1/workspaces/{ws_id}/projects",
            headers=h,
            json={
                "name": "Apollo",
                "objective": "Ra mắt nền tảng",
                "leader": {"description": "Điều phối dự án.", "marius_id": None},
                "roles": [{"title": "Backend", "seats": 1, "description": "Lo máy chủ."}],
            },
        )
    assert r.status_code == 422, r.text


async def test_no_door_left_can_make_rename_or_delete_a_role() -> None:
    async with await _client() as c:
        h, ws_id = await _register(c, "join4@armarius.dev")
        pid = (await _project(c, ws_id, h))["id"]

        made = await c.post(
            f"/v1/projects/{pid}/roles",
            headers=h,
            json={"title": "QA", "seats": 1, "description": "Kiểm thử."},
        )
        renamed = await c.patch(
            f"/v1/projects/{pid}/roles/{MEMBERS_ROLE_KEY}", headers=h, json={"title": "Đội"}
        )
        dropped = await c.delete(f"/v1/projects/{pid}/roles/{MEMBERS_ROLE_KEY}", headers=h)
        # Cửa cấp ghế theo khoá vai cũng đi cùng: nó là bước hai của đúng đường ấy.
        granted = await c.post(
            f"/v1/projects/{pid}/grant",
            headers=h,
            json={"role_key": MEMBERS_ROLE_KEY, "marius_id": str(uuid4())},
        )

    for r in (made, renamed, dropped, granted):
        assert r.status_code == 404, f"{r.request.method} {r.request.url} → {r.status_code}"


# ── 3. gói tin không còn mô tả công việc do người chủ gõ ──────────────────────


async def test_what_a_member_is_told_about_itself_comes_from_its_own_instructions() -> None:
    """Chỗ ngồi không nói agent làm gì — nó trỏ về instructions của chính agent.

    Đây là điều FR-007l muốn: một bản mô tả cách cư xử, ở một chỗ. Nếu vai còn sống thì câu
    người chủ gõ vào vai sẽ nằm trong gói tin, đứng cạnh instructions và lệch dần khỏi nó.
    """
    async with await _client() as c:
        h, ws_id = await _register(c, "join5@armarius.dev")
        lead, _ = await invite_and_online(c, ws_id, h, name="Trưởng")
        made = await _project(
            c, ws_id, h, leader={"description": "Điều phối dự án.", "marius_id": lead}
        )
        pid = made["id"]

        # Không dùng lối "mời rồi cho sống bằng một lượt chạy" ở đây: lượt chạy ấy chiếm chỗ
        # trên máy, và lượt chạy mà bài kiểm này cần mở sẽ không còn chỗ nào để đậu.
        worker = await invite_agent(
            c, ws_id, h,
            name="Thợ-máy-chủ",
            instructions="Bạn lo phần máy chủ và không đụng vào giao diện.",
        )
        wid = worker["id"]
        await app.state.container.liveness.record_signal(UUID(wid))
        joined = await c.post(f"/v1/projects/{pid}/members", headers=h, json={"marius_id": wid})
        assert joined.status_code == 201, joined.text

        await force_operating(pid)
        task = await c.post(
            f"/v1/projects/{pid}/tasks",
            headers=h,
            json={
                "title": "Dựng lối đăng nhập",
                # Không có brief thì không ai được gọi dậy — cổng ấy là chuyện khác, ở đây chỉ
                # cần nó mở để đọc được gói tin.
                "description": "Dựng màn hình đăng nhập và nối vào lối xác thực.",
                "assigned_marius_id": wid,
            },
        )
        assert task.status_code == 201, task.text
        tid = task.json()["id"]

        # Một lượt chạy về đúng đầu việc ấy, rồi đọc gói tin nó mang. Mở bằng tay chứ không
        # chờ cú gọi dậy thật: chỗ đang đo là **nội dung** gói tin, và đợi bộ điều phối sẽ
        # biến bài kiểm này thành bài kiểm về cú gọi dậy.
        run = await open_run(marius_id=wid, task_id=tid)
        packet = await app.state.container.wake_engine.compose_packet(run.run_id)

    assert packet is not None
    # Instructions của chính nó đi kèm, nguyên văn.
    assert "Bạn lo phần máy chủ và không đụng vào giao diện." in packet.prompt
    # Còn chỗ nó ngồi thì chỉ **trỏ về** instructions ấy. Đo cái tính chất, không đo cái hằng
    # số: so gói tin với chính hằng số thì đổi hằng số thành một bản mô tả công việc vẫn xanh —
    # phép đột biến ấy sống sót một lần rồi (m6), và nó chính là thứ FR-007l cấm.
    assert MEMBERS_ROLE_DESCRIPTION in packet.prompt
    assert "instructions" in MEMBERS_ROLE_DESCRIPTION.lower(), (
        "dòng chỗ ngồi chung phải nói rõ cách cư xử đến từ instructions của chính agent, "
        f"chứ không tự mô tả công việc: {MEMBERS_ROLE_DESCRIPTION!r}"
    )


# ── 4. một chỗ đã hứa với ai thì có trần; chỗ ngồi chung thì không ────────────


async def test_the_leader_seat_holds_one_and_the_bench_holds_everyone() -> None:
    async with await _client() as c:
        h, ws_id = await _register(c, "join6@armarius.dev")
        pid = (await _project(c, ws_id, h))["id"]
        first, _ = await invite_and_online(c, ws_id, h, name="Một")
        second, _ = await invite_and_online(c, ws_id, h, name="Hai")

        assert (
            await c.post(f"/v1/projects/{pid}/leader", headers=h, json={"marius_id": first})
        ).status_code == 201
        taken = await c.post(
            f"/v1/projects/{pid}/leader", headers=h, json={"marius_id": second}
        )

        for who in (second,):
            assert (
                await c.post(f"/v1/projects/{pid}/members", headers=h, json={"marius_id": who})
            ).status_code == 201
        third, _ = await invite_and_online(c, ws_id, h, name="Ba")
        more = await c.post(f"/v1/projects/{pid}/members", headers=h, json={"marius_id": third})

    assert taken.status_code == 400, taken.text
    assert taken.json()["code"] == "role_seats_full"
    assert more.status_code == 201, more.text
