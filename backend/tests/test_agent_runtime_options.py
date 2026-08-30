"""Thứ đặt được cho một agent là câu trả lời của **chỗ làm**, không phải của người gọi (T039g).

FR-007k đòi hai điều, và điều thứ hai mới là điều khó: người dùng chọn được model với mức suy
nghĩ, **và** danh sách chọn phải lấy từ khả năng thật của chỗ làm chứ không từ một bảng chép
cứng theo tên CLI (FR-017).

Đây là chỗ luật ấy thành thật. Cùng một loại CLI, cùng một cái tên, **khác thứ máy khai lên** —
và danh sách phải khác theo. Một bài kiểm chỉ dựng đúng một chỗ làm rồi khẳng định "có model
đấy" sẽ xanh y hệt trên một bản cài đọc bảng chép cứng, tức là không kiểm gì cả.

**Vì sao chặn ở tầng use case chứ không chỉ ở màn hình.** Màn hình dựng danh sách từ cùng dữ
liệu ấy nên nó giữ cho người dùng thật đi đúng — nhưng nó chỉ là một trong hai đường vào, đường
kia là ai đó gọi thẳng API. Một luật chỉ có ở màn hình là một luật chỉ áp cho người tử tế.
"""

from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import update

from armarius.infrastructure.daemon.models import WorkplaceModel
from armarius.infrastructure.database.engine import get_sessionmaker
from armarius.main import app
from tests.support.machines import auth, link_machine

pytestmark = pytest.mark.anyio


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def _declares(workplace_id: str, choices: list[dict] | None) -> None:
    """Ghi lại thứ cái máy khai — đúng chỗ và đúng hình dạng daemon thật gửi lên."""
    async with get_sessionmaker()() as session:
        await session.execute(
            update(WorkplaceModel)
            .where(WorkplaceModel.id == UUID(workplace_id))
            .values(capabilities={"resumable": True, "choices": choices or []})
        )
        await session.commit()


_CLAUDE_LIKE = [
    {"key": "thinking_level", "values": ["low", "high", "max"], "source": "tool_declared"},
    {"key": "model", "values": ["opus", "sonnet"], "source": "tool_examples"},
]


async def _agent(c: AsyncClient, machine, name: str, **body) -> object:
    return await c.post(
        f"/v1/workspaces/{machine.workspace_id}/mariuses",
        json={"name": name, "workplace_id": machine.workplace_id, **body},
        headers=machine.headers,
    )


# ── 1. danh sách đi ra từ thứ cái máy khai, không từ tên CLI ─────────────────


async def test_the_same_kind_of_cli_offers_different_settings_when_it_answered_differently():
    """Bài quan trọng nhất của cả tệp: hai chỗ làm **cùng loại**, hai câu trả lời khác nhau.

    Một bản cài dựng danh sách từ bảng chép cứng theo `cli_kind` sẽ trả về **y hệt nhau** cho
    cả hai, và bài này đỏ. Không có cách nào làm nó xanh mà vẫn đọc bảng theo tên.
    """
    async with _client() as c:
        rich = await link_machine(c, f"rich-{uuid4().hex[:8]}@example.com", hostname="rich")
        await _declares(rich.workplace_id, _CLAUDE_LIKE)
        # Cùng workspace, cùng `claude_code`, nhưng bản trên máy này khai ít hơn hẳn — đúng ca
        # một người cài bản cũ trên máy thứ hai.
        plain = await c.post(
            "/daemon/link/start",
            json={"platform": "linux", "daemon_version": "0.1.0", "hostname": "plain"},
        )
        code = plain.json()["code"]
        await c.post(
            f"/v1/machines/link/{code}/approve",
            json={"workspace_id": rich.workspace_id},
            headers=rich.headers,
        )
        token = (await c.post("/daemon/link/poll", json={"code": code})).json()["token"]
        synced = await c.put(
            "/daemon/workplaces",
            json={
                "workplaces": [
                    {
                        "cli_kind": "claude_code",
                        "cli_version": "0.9.0",
                        "protocol_family": "one_shot",
                        "capabilities": {"resumable": True},
                    }
                ],
                "symlink_capable": True,
            },
            headers=auth(token),
        )
        plain_id = synced.json()["workplaces"][0]["id"]

        offered = await c.get(
            f"/v1/workspaces/{rich.workspace_id}/workplaces", headers=rich.headers
        )
        assert offered.status_code == 200, offered.text
        by_id = {w["id"]: w for w in offered.json()}

        assert {o["key"] for o in by_id[rich.workplace_id]["options"]} == {
            "thinking_level",
            "model",
        }
        assert by_id[plain_id]["options"] == [], (
            "chỗ làm không khai gì mà vẫn được bày ra lựa chọn — danh sách đang đến từ tên CLI, "
            "không từ thứ cái máy trả lời"
        )


async def test_the_screen_is_told_how_firmly_each_list_is_known():
    """Bộ đầy đủ và mấy cái ví dụ hiện lên khác nhau, nên phải phân biệt được từ dữ liệu.

    Bày ví dụ y như một bộ đóng là từ chối một giá trị hợp lệ ngay trên màn hình, vào đúng
    ngày tool có thêm cái thứ tư.
    """
    async with _client() as c:
        machine = await link_machine(c, f"s-{uuid4().hex[:8]}@example.com", hostname="box")
        await _declares(machine.workplace_id, _CLAUDE_LIKE)

        offered = await c.get(
            f"/v1/workspaces/{machine.workspace_id}/workplaces", headers=machine.headers
        )
        sources = {o["key"]: o["source"] for o in offered.json()[0]["options"]}
        assert sources == {"thinking_level": "tool_declared", "model": "tool_examples"}


async def test_a_workplace_that_offers_nothing_is_ordinary_rather_than_broken():
    async with _client() as c:
        machine = await link_machine(c, f"n-{uuid4().hex[:8]}@example.com", hostname="box")
        await _declares(machine.workplace_id, None)

        offered = await c.get(
            f"/v1/workspaces/{machine.workspace_id}/workplaces", headers=machine.headers
        )
        assert offered.status_code == 200
        assert offered.json()[0]["options"] == []

        # Và vẫn tạo được agent ở đó — chỉ là không có gì để chọn.
        made = await _agent(c, machine, "Marin")
        assert made.status_code == 201, made.text


# ── 2. chọn cái chỗ làm không mời thì bị từ chối ─────────────────────────────


async def test_what_was_picked_is_kept_and_comes_back():
    async with _client() as c:
        machine = await link_machine(c, f"k-{uuid4().hex[:8]}@example.com", hostname="box")
        await _declares(machine.workplace_id, _CLAUDE_LIKE)

        made = await _agent(
            c, machine, "Marin", runtime_options={"model": "opus", "thinking_level": "high"}
        )
        assert made.status_code == 201, made.text

        listed = await c.get(
            f"/v1/workspaces/{machine.workspace_id}/mariuses", headers=machine.headers
        )
        kept = next(m for m in listed.json() if m["name"] == "Marin")
        assert kept["runtime_options"] == {"model": "opus", "thinking_level": "high"}


async def test_a_setting_this_workplace_never_offered_is_refused():
    """Đường vào thứ hai — gọi thẳng API, không qua màn hình — vẫn phải bị chặn."""
    async with _client() as c:
        machine = await link_machine(c, f"u-{uuid4().hex[:8]}@example.com", hostname="box")
        await _declares(machine.workplace_id, _CLAUDE_LIKE)

        refused = await _agent(
            c, machine, "Marin", runtime_options={"service_tier": "priority"}
        )
        assert refused.status_code == 422, refused.text
        assert refused.json().get("code") == "placement_option_unknown"


async def test_a_value_outside_a_complete_set_is_refused():
    async with _client() as c:
        machine = await link_machine(c, f"v-{uuid4().hex[:8]}@example.com", hostname="box")
        await _declares(machine.workplace_id, _CLAUDE_LIKE)

        refused = await _agent(
            c, machine, "Marin", runtime_options={"thinking_level": "nuclear"}
        )
        assert refused.status_code == 422, refused.text
        assert refused.json().get("code") == "placement_option_value_unsupported"


async def test_a_value_outside_a_list_of_examples_is_accepted():
    """Ví dụ là ví dụ. Từ chối `haiku` vì tool chỉ kịp kể ba cái tên là từ chối một model thật."""
    async with _client() as c:
        machine = await link_machine(c, f"e-{uuid4().hex[:8]}@example.com", hostname="box")
        await _declares(machine.workplace_id, _CLAUDE_LIKE)

        made = await _agent(c, machine, "Marin", runtime_options={"model": "haiku"})
        assert made.status_code == 201, made.text


async def test_leaving_a_setting_blank_stays_blank_rather_than_being_refused():
    """FR-007k: bỏ trống nghĩa là dùng mặc định của chính tool, nên chuỗi rỗng phải đi lọt."""
    async with _client() as c:
        machine = await link_machine(c, f"b-{uuid4().hex[:8]}@example.com", hostname="box")
        await _declares(machine.workplace_id, _CLAUDE_LIKE)

        made = await _agent(c, machine, "Marin", runtime_options={"thinking_level": ""})
        assert made.status_code == 201, made.text


# ── 3. thứ đã chọn phải đi xuống được tới cái máy ────────────────────────────


async def test_what_was_picked_travels_down_with_the_work():
    """Chọn xong mà không xuống tới máy thì cả tính năng chỉ là một ô trên màn hình.

    Đi qua **cửa nhận việc thật**: đặt việc lên kệ rồi để máy tới xin, y như lúc chạy thật.
    """
    from tests.support.work import a_project, a_task, shelve

    async with _client() as c:
        machine = await link_machine(c, f"d-{uuid4().hex[:8]}@example.com", hostname="box")
        await _declares(machine.workplace_id, _CLAUDE_LIKE)
        made = await _agent(
            c, machine, "Marin", runtime_options={"model": "opus", "thinking_level": "high"}
        )
        marius_id = made.json()["id"]

        project_id = await a_project(machine.workspace_id)
        task_id = await a_task(project_id, assigned_to=marius_id)
        await shelve(marius_id=marius_id, task_id=task_id)

        handed = await c.post(
            "/daemon/runs/claim",
            json={"workplace_ids": [machine.workplace_id], "max": 1},
            # Token của **máy**, không phải của người: cửa daemon xác thực cái máy.
            headers=auth(machine.token),
        )
        assert handed.status_code == 200, handed.text
        runs = handed.json()["runs"]
        assert runs, "không nhận được việc nào"
        assert runs[0]["runtime_options"] == {"model": "opus", "thinking_level": "high"}


async def test_an_agent_that_picked_nothing_sends_nothing_down():
    """Không phải chuyện gọn gàng: máy dịch mỗi khoá thành một cái cờ, và một cờ rỗng là một
    lượt chạy hỏng lúc khởi chạy thay vì một lượt chạy dùng mặc định."""
    from tests.support.work import a_project, a_task, shelve

    async with _client() as c:
        machine = await link_machine(c, f"z-{uuid4().hex[:8]}@example.com", hostname="box")
        await _declares(machine.workplace_id, _CLAUDE_LIKE)
        made = await _agent(c, machine, "Marin")
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
        assert handed.json()["runs"][0]["runtime_options"] == {}
