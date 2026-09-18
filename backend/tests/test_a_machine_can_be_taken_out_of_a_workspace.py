"""Gỡ được một máy khỏi workspace, và giấy tờ của nó đi theo (FR-001d, T159).

*Người chủ hỏi 2026-09-07: "tại sao thêm máy lại không xóa được máy?"* — và kiểm hết cửa thì đúng
là **không có gì**: nối vào thì có, xem và đổi trần thì có, gỡ ra thì không.

Đây không phải chuyện gọn gàng. Mỗi máy đã nối giữ một **token còn sống**, nên một cái máy cho
nghỉ, bán đi hay mất đều giữ giấy tờ đi làm chừng nào hàng của nó còn đứng đó, và không ai thu lại
được. FR-001 cho một đường vào mà không có đường ra.

Ba thứ bài này giữ, và thứ tự quan trọng:

  1. **Giấy tờ chết.** Token của máy ấy không còn mở được cửa nào nữa. Đây là nửa đáng giá.
  2. **Agent sống sót.** Chúng thành *chưa có chỗ làm* — một trạng thái có nghĩa đã định và có
     đường về — chứ không bị xoá cùng. Xoá chúng là ném đi lịch sử lượt chạy và chỗ ngồi trong dự
     án vì một sự thật về cái máy.
  3. **Máy của người khác đọc y như máy không tồn tại** (Hiến pháp I).
"""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from armarius.main import app
from tests.support.agents import invite_agent
from tests.support.machines import auth, link_machine
from tests.support.work import a_project, a_task, shelve

pytestmark = pytest.mark.anyio


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def test_removing_a_machine_kills_its_credential() -> None:
    """Nửa đáng giá nhất: token của máy đã gỡ không mở được cửa nào nữa."""
    async with _client() as c:
        box = await link_machine(c, "machine-revoke@armarius.dev")

        # Trước khi gỡ, giấy tờ ấy dùng được.
        beat = await c.post("/daemon/heartbeat", json={}, headers=auth(box.token))
        assert beat.status_code == 200, beat.text

        gone = await c.delete(
            f"/v1/workspaces/{box.workspace_id}/machines/{box.machine_id}",
            headers=box.headers,
        )
        assert gone.status_code == 204, gone.text

        # Sau khi gỡ, cùng cái token ấy không còn là ai cả.
        refused = await c.post("/daemon/heartbeat", json={}, headers=auth(box.token))
        assert refused.status_code == 401, refused.text


async def test_the_machine_is_gone_from_the_list() -> None:
    async with _client() as c:
        box = await link_machine(c, "machine-list@armarius.dev")
        before = await c.get(
            f"/v1/workspaces/{box.workspace_id}/machines", headers=box.headers
        )
        assert [m["id"] for m in before.json()] == [str(box.machine_id)], before.json()

        await c.delete(
            f"/v1/workspaces/{box.workspace_id}/machines/{box.machine_id}",
            headers=box.headers,
        )

        after = await c.get(
            f"/v1/workspaces/{box.workspace_id}/machines", headers=box.headers
        )
        assert after.json() == [], after.json()


async def test_agents_that_lived_there_survive_as_unplaced() -> None:
    """Agent **không** bị xoá theo. Nó thành chưa-có-chỗ-làm, và đó là đường về."""
    async with _client() as c:
        box = await link_machine(c, "machine-agents@armarius.dev")
        agent = await invite_agent(
            c, box.workspace_id, box.headers, name="Marin", workplace_id=box.workplace_id
        )

        await c.delete(
            f"/v1/workspaces/{box.workspace_id}/machines/{box.machine_id}",
            headers=box.headers,
        )

        listed = await c.get(
            f"/v1/workspaces/{box.workspace_id}/mariuses", headers=box.headers
        )
        rows = {a["id"]: a for a in listed.json()}
        assert agent["id"] in rows, "agent bị xoá theo máy — không được"
        mine = rows[agent["id"]]
        assert mine["liveness"] == "offline", mine
        assert mine["offline_reason"] == "not_placed", mine


async def test_a_machine_holding_work_can_still_be_removed() -> None:
    """Máy đang cầm việc vẫn gỡ được — đó đúng là cái máy người ta muốn thu giấy tờ nhất."""
    async with _client() as c:
        box = await link_machine(c, "machine-busy@armarius.dev")
        agent = await invite_agent(
            c, box.workspace_id, box.headers, name="Marin", workplace_id=box.workplace_id
        )
        project_id = await a_project(box.workspace_id)
        task_id = await a_task(project_id, assigned_to=agent["id"])
        await shelve(marius_id=agent["id"], task_id=task_id)
        taken = await c.post(
            "/daemon/runs/claim",
            json={"workplace_ids": [box.workplace_id], "max": 1},
            headers=auth(box.token),
        )
        assert len(taken.json()["runs"]) == 1, taken.text
        held = taken.json()["runs"][0]

        gone = await c.delete(
            f"/v1/workspaces/{box.workspace_id}/machines/{box.machine_id}",
            headers=box.headers,
        )
        assert gone.status_code == 204, gone.text

        # Và cái daemon vẫn còn sống ngoài kia nhận về một lời từ chối sạch, không phải một cú vỡ.
        reported = await c.post(
            f"/daemon/runs/{held['run_id']}/finish",
            json={"status": "completed"},
            headers={"Authorization": f"Bearer {held['run_token']}"},
        )
        assert reported.status_code in (401, 404), reported.text


async def test_a_stranger_cannot_remove_a_machine_and_cannot_tell_it_is_there() -> None:
    async with _client() as c:
        mine = await link_machine(c, "machine-mine@armarius.dev")
        theirs = await link_machine(c, "machine-theirs@armarius.dev")

        # Người ngoài gọi vào workspace của họ, với id máy của tôi: 404, không phải 403.
        refused = await c.delete(
            f"/v1/workspaces/{theirs.workspace_id}/machines/{mine.machine_id}",
            headers=theirs.headers,
        )
        assert refused.status_code == 404, refused.text
        assert refused.json()["code"] == "machine_not_found", refused.json()

        # Và máy của tôi vẫn còn nguyên.
        still = await c.get(
            f"/v1/workspaces/{mine.workspace_id}/machines", headers=mine.headers
        )
        assert [m["id"] for m in still.json()] == [str(mine.machine_id)], still.json()


async def test_removing_a_machine_that_is_not_there_is_not_there() -> None:
    from uuid import uuid4

    async with _client() as c:
        box = await link_machine(c, "machine-nosuch@armarius.dev")
        missing = await c.delete(
            f"/v1/workspaces/{box.workspace_id}/machines/{uuid4()}", headers=box.headers
        )
        assert missing.status_code == 404, missing.text
