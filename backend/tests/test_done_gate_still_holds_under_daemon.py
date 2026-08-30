"""Cổng *chưa có hiện vật thì chưa rời đang làm* phải đứng cả trên đường daemon (T093).

Cổng ấy đã có bài kiểm — ở tầng thực thể, gọi thẳng hàm chuyển trạng thái. Đó là bài kiểm
**luật**, và luật thì đúng. Nhưng luật đúng ở tầng dưới vẫn bị tầng trên gỡ mất mà không bài
nào đỏ: đường đi thật của một agent chạy trên máy người dùng là **token của lượt chạy → lối
HTTP → use case → thực thể**, và mỗi chặng ấy là một chỗ luật có thể rơi. Cho tới bài này,
không một bài kiểm nào nhắc tới mã từ chối `task_needs_artifact` — nghĩa là cổng chưa từng
được đi thử qua cửa mà người ta thật sự gõ.

Ba điều phải cùng đúng, và không điều nào suy ra được từ hai điều kia (Điều II, SC-004, FR-020):

  1. Chưa công bố hiện vật thì **không rời được** *đang làm* — 409 với mã, không phải 500.
  2. Bị chặn rồi thì đầu việc **vẫn giữ động cơ đẩy**. Một cổng chặn xong bỏ đấy là một đầu
     việc đứng im vĩnh viễn: agent không đi tiếp được, mà cũng không còn gì đẩy nó nữa.
  3. Hiện vật đã ghi nhận thì **tải về được thật** — đọc lại từ kho và so đúng byte. Một hàng
     trong bảng trỏ vào chỗ trống mở cổng ra bằng một lời hứa suông.

Đi qua **cửa nhận việc thật**: đặt việc lên kệ, để máy tới xin, rồi dùng chính token lượt chạy
mà cửa ấy trả về. Không dùng token người dùng — đó là đường khác, và nó không phải đường agent đi.
"""

from __future__ import annotations

import hashlib
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from armarius.main import app
from tests.support.machines import auth, link_machine
from tests.support.work import a_project, a_task, shelve

pytestmark = pytest.mark.anyio

_BYTES = b"# Report\n\nEverything the patron asked for.\n"


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def _a_run_in_hand(c: AsyncClient, machine) -> tuple[UUID, str]:
    """Một agent, một đầu việc của nó, và lượt chạy đã nằm trong tay máy."""
    made = await c.post(
        f"/v1/workspaces/{machine.workspace_id}/mariuses",
        json={"name": f"Marin-{uuid4().hex[:6]}", "workplace_id": machine.workplace_id},
        headers=machine.headers,
    )
    assert made.status_code == 201, made.text
    marius_id = made.json()["id"]

    project_id = await a_project(machine.workspace_id)
    task_id = await a_task(project_id, assigned_to=marius_id)
    await shelve(marius_id=marius_id, task_id=task_id)

    handed = await c.post(
        "/daemon/runs/claim",
        json={"workplace_ids": [machine.workplace_id], "max": 1},
        headers=auth(machine.token),
    )
    assert handed.status_code == 200, handed.text
    runs = handed.json()["runs"]
    assert runs, "cửa nhận việc không đưa việc nào"
    run_token = runs[0]["run_token"]

    # Đầu việc phải đang *đang làm* thì cổng hiện vật mới là thứ chặn. Từ *cần làm* thì luật
    # chuyển trạng thái chặn trước, và một bài kiểm dừng ở đó sẽ xanh trên một bản cài **không
    # có cổng hiện vật nào cả** — nó mới chỉ chứng minh bảng chuyển trạng thái còn nguyên.
    started = await c.post(
        f"/agent/tasks/{task_id}/status",
        json={"status": "in_progress"},
        headers=auth(run_token),
    )
    assert started.status_code == 200, started.text
    return task_id, run_token


async def _publish(c: AsyncClient, task_id: UUID, run_token: str, name: str = "report.md"):
    import base64

    return await c.post(
        f"/agent/tasks/{task_id}/artifact",
        json={
            "name": name,
            "kind": "file",
            "content_b64": base64.b64encode(_BYTES).decode(),
            "content_sha256": hashlib.sha256(_BYTES).hexdigest(),
        },
        headers=auth(run_token),
    )


async def test_an_agent_on_a_machine_cannot_leave_in_progress_without_an_artifact():
    """Đường vào thật của agent: token lượt chạy, lối HTTP, đúng đầu việc của nó."""
    async with _client() as c:
        machine = await link_machine(c, f"gate-{uuid4().hex[:8]}@example.com", hostname="box")
        task_id, run_token = await _a_run_in_hand(c, machine)

        refused = await c.post(
            f"/agent/tasks/{task_id}/status",
            json={"status": "in_review"},
            headers=auth(run_token),
        )
        # 409 chứ không 500: đây là một xung đột trạng thái có tên, và cái tên ấy là thứ màn
        # hình dựng câu tiếng Việt từ đó (Điều VII).
        assert refused.status_code == 409, refused.text
        assert refused.json().get("code") == "task_needs_artifact", refused.text

        # Và đầu việc **ở nguyên chỗ cũ**. Một cổng từ chối lời gọi rồi vẫn để trạng thái đi
        # tiếp là một cổng chỉ có trong câu trả lời, không có trong dữ liệu.
        shown = await c.get(f"/v1/tasks/{task_id}", headers=machine.headers)
        assert shown.json()["status"] == "in_progress", shown.text


async def test_being_blocked_leaves_the_task_with_something_still_pushing_it():
    """Chặn mà lấy luôn động cơ đẩy là dựng ra một đầu việc không ai đẩy và cũng không ai đi.

    Đây là nửa dễ quên: cổng làm đúng việc của nó rồi, và cái hỏng nằm ở thứ nó **không** làm.
    """
    async with _client() as c:
        machine = await link_machine(c, f"push-{uuid4().hex[:8]}@example.com", hostname="box")
        task_id, run_token = await _a_run_in_hand(c, machine)

        refused = await c.post(
            f"/agent/tasks/{task_id}/status",
            json={"status": "in_review"},
            headers=auth(run_token),
        )
        assert refused.status_code == 409, refused.text

        shown = await c.get(f"/v1/tasks/{task_id}", headers=machine.headers)
        assert shown.status_code == 200, shown.text
        assert shown.json()["drive"], (
            "bị chặn xong đầu việc mất luôn động cơ đẩy — nó sẽ đứng im mà không ai biết"
        )


async def test_the_artifact_that_opened_the_gate_is_really_there_to_download():
    """Cổng mở ra vì có một hàng trong bảng. Bài này hỏi hàng ấy có thật không.

    Đọc lại **từ kho**, so từng byte và so cả hash: một hàng trỏ vào chỗ trống vẫn mở được
    cổng, và người chủ chỉ phát hiện lúc bấm tải về (FR-020, FR-020b).
    """
    async with _client() as c:
        machine = await link_machine(c, f"art-{uuid4().hex[:8]}@example.com", hostname="box")
        task_id, run_token = await _a_run_in_hand(c, machine)

        published = await _publish(c, task_id, run_token)
        assert published.status_code == 201, published.text
        recorded = published.json()
        assert recorded["content_sha256"] == hashlib.sha256(_BYTES).hexdigest()

        store = app.state.container.artifact_store
        back = await store.read_bytes(recorded["uri"])
        assert back == _BYTES, "hiện vật đã ghi nhận nhưng đọc lại ra thứ khác"


async def test_once_the_artifact_is_published_the_same_call_goes_through():
    """Nửa còn lại của cổng. Chỉ kiểm vế chặn thì một cổng chặn *mọi* thứ cũng xanh."""
    async with _client() as c:
        machine = await link_machine(c, f"open-{uuid4().hex[:8]}@example.com", hostname="box")
        task_id, run_token = await _a_run_in_hand(c, machine)

        assert (await _publish(c, task_id, run_token)).status_code == 201

        moved = await c.post(
            f"/agent/tasks/{task_id}/status",
            json={"status": "in_review"},
            headers=auth(run_token),
        )
        assert moved.status_code == 200, moved.text
        assert moved.json()["status"] == "in_review"
