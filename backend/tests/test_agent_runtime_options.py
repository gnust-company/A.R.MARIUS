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


# ── 4. đổi được thứ đã đặt, trên một agent đã tạo (T039k) ────────────────────
#
# Trước T039k, muốn hạ mức nghĩ của một agent thì phải **xoá nó rồi tạo lại** — vứt luôn tên,
# chỉ dẫn, kỹ năng đã nối và cả lịch sử chạy, chỉ để đổi một ô. Cửa sửa vốn có, chỉ là không
# nhận ô ấy (người review chỉ ra ở PR #239).


async def _patch(c: AsyncClient, machine, marius_id: str, **body):
    return await c.patch(
        f"/v1/workspaces/{machine.workspace_id}/mariuses/{marius_id}",
        json=body,
        headers=machine.headers,
    )


async def _read(c: AsyncClient, machine, marius_id: str) -> dict:
    listed = await c.get(
        f"/v1/workspaces/{machine.workspace_id}/mariuses", headers=machine.headers
    )
    return next(m for m in listed.json() if m["id"] == marius_id)


async def test_what_an_agent_was_set_to_can_be_changed_without_deleting_it():
    async with _client() as c:
        machine = await link_machine(c, f"p1-{uuid4().hex[:8]}@example.com", hostname="box")
        await _declares(machine.workplace_id, _CLAUDE_LIKE)
        made = await _agent(
            c, machine, "Marin", runtime_options={"model": "opus", "thinking_level": "high"}
        )
        marius_id = made.json()["id"]

        changed = await _patch(c, machine, marius_id, runtime_options={"thinking_level": "low"})
        assert changed.status_code == 200, changed.text
        assert (await _read(c, machine, marius_id))["runtime_options"]["thinking_level"] == "low"


async def test_only_the_settings_named_are_changed():
    """Sửa một ô là sửa một ô. Ô không được nhắc tới **không phải** ô bị xoá — nếu không thì
    mọi lần đổi model đều âm thầm ném mức nghĩ về mặc định của tool."""
    async with _client() as c:
        machine = await link_machine(c, f"p2-{uuid4().hex[:8]}@example.com", hostname="box")
        await _declares(machine.workplace_id, _CLAUDE_LIKE)
        made = await _agent(
            c, machine, "Marin", runtime_options={"model": "opus", "thinking_level": "high"}
        )
        marius_id = made.json()["id"]

        changed = await _patch(c, machine, marius_id, runtime_options={"model": "sonnet"})
        assert changed.status_code == 200, changed.text
        assert (await _read(c, machine, marius_id))["runtime_options"] == {
            "model": "sonnet",
            "thinking_level": "high",
        }


async def test_clearing_a_setting_puts_it_back_to_the_tools_own_default():
    """Vẫn phải nói được câu "thôi, để tool tự quyết" — FR-007k bảo bỏ trống nghĩa là thế."""
    async with _client() as c:
        machine = await link_machine(c, f"p3-{uuid4().hex[:8]}@example.com", hostname="box")
        await _declares(machine.workplace_id, _CLAUDE_LIKE)
        made = await _agent(c, machine, "Marin", runtime_options={"thinking_level": "high"})
        marius_id = made.json()["id"]

        cleared = await _patch(c, machine, marius_id, runtime_options={"thinking_level": ""})
        assert cleared.status_code == 200, cleared.text
        assert (await _read(c, machine, marius_id))["runtime_options"]["thinking_level"] == ""


async def test_the_edit_door_refuses_what_the_create_door_refuses():
    """Một luật chỉ chặn ở một cửa thì không phải luật — bài học của PR #256, ở đây là hai cửa
    đặt cùng một thứ."""
    async with _client() as c:
        machine = await link_machine(c, f"p4-{uuid4().hex[:8]}@example.com", hostname="box")
        await _declares(machine.workplace_id, _CLAUDE_LIKE)
        marius_id = (await _agent(c, machine, "Marin")).json()["id"]

        unknown = await _patch(
            c, machine, marius_id, runtime_options={"service_tier": "priority"}
        )
        outside = await _patch(
            c, machine, marius_id, runtime_options={"thinking_level": "nuclear"}
        )
        assert unknown.status_code == 422, unknown.text
        assert unknown.json().get("code") == "placement_option_unknown"
        assert outside.status_code == 422, outside.text
        assert outside.json().get("code") == "placement_option_value_unsupported"
        assert (await _read(c, machine, marius_id))["runtime_options"] == {}


async def test_a_value_that_went_stale_does_not_block_an_edit_that_never_touched_it():
    """Cái bẫy thật của việc cho sửa, và nó không tự lộ ra ở đường hạnh phúc.

    Thứ chỗ làm nhận là câu trả lời của tool **lần gần nhất được hỏi**, và câu ấy đổi: máy nâng
    cấp, tool bỏ một mức. Giá trị lưu từ tháng trước bỗng nằm ngoài danh sách hôm nay. Nếu bản
    sửa được đo trên **kết quả trộn** thì đổi tên cũng bị từ chối — một việc chưa từng đi gần ô
    đã cũ — và người dùng không có đường nào biết vì sao.
    """
    async with _client() as c:
        machine = await link_machine(c, f"p5-{uuid4().hex[:8]}@example.com", hostname="box")
        await _declares(machine.workplace_id, _CLAUDE_LIKE)
        made = await _agent(
            c, machine, "Marin", runtime_options={"thinking_level": "max", "model": "opus"}
        )
        marius_id = made.json()["id"]

        # Máy được nâng cấp; bản mới không còn mức `max`.
        await _declares(
            machine.workplace_id,
            [
                {
                    "key": "thinking_level",
                    "values": ["low", "high"],
                    "source": "tool_declared",
                },
                {"key": "model", "values": ["opus", "sonnet"], "source": "tool_examples"},
            ],
        )

        renamed = await _patch(c, machine, marius_id, name="Marin the Second")
        elsewhere = await _patch(c, machine, marius_id, runtime_options={"model": "sonnet"})
        assert renamed.status_code == 200, renamed.text
        assert elsewhere.status_code == 200, elsewhere.text
        kept = await _read(c, machine, marius_id)
        assert kept["runtime_options"] == {"thinking_level": "max", "model": "sonnet"}, (
            "giá trị đã cũ bị bản sửa cuốn đi hoặc chặn bản sửa — cả hai đều là đo trên kết "
            "quả trộn thay vì đo đúng thứ lần này được chọn"
        )
        # Còn chọn *lại* chính cái mức đã biến mất thì vẫn phải bị từ chối: lúc ấy nó đúng là
        # thứ đang được chọn.
        again = await _patch(c, machine, marius_id, runtime_options={"thinking_level": "max"})
        assert again.status_code == 422, again.text
        assert again.json().get("code") == "placement_option_value_unsupported"


async def test_the_change_reaches_the_next_run_and_not_the_one_already_handed_out():
    """Câu trả lời trung thực là *lượt sau*, và đây là chỗ nó thành thật đo được.

    Gói việc đọc thứ đã đặt lúc cái máy tới nhận việc, rồi mang theo xuống. Việc đã rời server
    thì không còn đường nào với tới — nên màn hình phải nói ra điều ấy chứ không im lặng.
    """
    from tests.support.work import a_project, a_task, shelve

    async with _client() as c:
        machine = await link_machine(c, f"p6-{uuid4().hex[:8]}@example.com", hostname="box")
        await _declares(machine.workplace_id, _CLAUDE_LIKE)
        made = await _agent(c, machine, "Marin", runtime_options={"thinking_level": "high"})
        marius_id = made.json()["id"]

        project_id = await a_project(machine.workspace_id)
        first = await a_task(project_id, assigned_to=marius_id)
        await shelve(marius_id=marius_id, task_id=first)
        handed = await c.post(
            "/daemon/runs/claim",
            json={"workplace_ids": [machine.workplace_id], "max": 1},
            headers=auth(machine.token),
        )
        assert handed.status_code == 200, handed.text
        already_out = handed.json()["runs"][0]

        changed = await _patch(c, machine, marius_id, runtime_options={"thinking_level": "low"})
        assert changed.status_code == 200, changed.text

        # Việc trước phải khép lại đã: một agent nhận một lượt một lúc, nên không đóng thì
        # cái máy quay lại cũng ra tay không và bài kiểm sẽ đo nhầm sang luật đó.
        closed = await c.post(
            f"/daemon/runs/{already_out['run_id']}/finish",
            json={"status": "completed"},
            headers=auth(machine.token),
        )
        assert closed.status_code == 200, closed.text

        second = await a_task(project_id, assigned_to=marius_id)
        await shelve(marius_id=marius_id, task_id=second)
        next_one = await c.post(
            "/daemon/runs/claim",
            json={"workplace_ids": [machine.workplace_id], "max": 1},
            headers=auth(machine.token),
        )
        assert next_one.status_code == 200, next_one.text

        assert already_out["runtime_options"] == {"thinking_level": "high"}
        assert next_one.json()["runs"][0]["runtime_options"] == {"thinking_level": "low"}


# ── 5. màn hình sửa hỏi chính agent, không hỏi danh sách chỗ để đặt agent mới ──


async def test_the_settings_an_agent_offers_come_from_the_place_it_works():
    async with _client() as c:
        machine = await link_machine(c, f"p7-{uuid4().hex[:8]}@example.com", hostname="box")
        await _declares(machine.workplace_id, _CLAUDE_LIKE)
        marius_id = (await _agent(c, machine, "Marin")).json()["id"]

        offered = await c.get(
            f"/v1/workspaces/{machine.workspace_id}/mariuses/{marius_id}/options",
            headers=machine.headers,
        )
        assert offered.status_code == 200, offered.text
        assert {o["key"]: o["source"] for o in offered.json()} == {
            "thinking_level": "tool_declared",
            "model": "tool_examples",
        }


async def test_an_agent_whose_cli_was_uninstalled_can_still_have_its_settings_changed():
    """Lý do tồn tại của cửa ấy, và nó không đo được ở đường hạnh phúc.

    Danh sách chỗ-để-đặt-agent-mới chỉ bày chỗ **còn nhận việc**, nên gỡ CLI đi là chỗ ấy rơi
    khỏi danh sách — và một màn hình sửa dựng từ danh sách ấy sẽ đọc thành *không có gì để
    chọn*. Thứ tool nhận không hết đúng vì có người gỡ nó ra rồi cài lại.
    """
    async with _client() as c:
        machine = await link_machine(c, f"p8-{uuid4().hex[:8]}@example.com", hostname="box")
        await _declares(machine.workplace_id, _CLAUDE_LIKE)
        marius_id = (await _agent(c, machine, "Marin")).json()["id"]

        async with get_sessionmaker()() as session:
            await session.execute(
                update(WorkplaceModel)
                .where(WorkplaceModel.id == UUID(machine.workplace_id))
                .values(ready=False, not_ready_reason="cli_removed")
            )
            await session.commit()

        picker = await c.get(
            f"/v1/workspaces/{machine.workspace_id}/workplaces", headers=machine.headers
        )
        offered = await c.get(
            f"/v1/workspaces/{machine.workspace_id}/mariuses/{marius_id}/options",
            headers=machine.headers,
        )
        changed = await _patch(c, machine, marius_id, runtime_options={"thinking_level": "low"})

        assert picker.json() == [], "chỗ làm đã đóng mà vẫn nằm trong danh sách để đặt agent mới"
        assert offered.status_code == 200, offered.text
        assert {o["key"] for o in offered.json()} == {"thinking_level", "model"}
        assert changed.status_code == 200, changed.text


async def test_the_settings_of_an_agent_in_another_workspace_read_as_no_such_agent():
    """Hiến pháp I: không phải của mình thì đọc y hệt không tồn tại."""
    async with _client() as c:
        mine = await link_machine(c, f"p9-{uuid4().hex[:8]}@example.com", hostname="box")
        theirs = await link_machine(c, f"pa-{uuid4().hex[:8]}@example.com", hostname="other")
        await _declares(theirs.workplace_id, _CLAUDE_LIKE)
        stranger = (await _agent(c, theirs, "Marin")).json()["id"]

        peeked = await c.get(
            f"/v1/workspaces/{mine.workspace_id}/mariuses/{stranger}/options",
            headers=mine.headers,
        )
        assert peeked.status_code == 404, peeked.text


async def test_the_agent_that_comes_back_from_the_create_door_carries_what_was_picked():
    """Cửa tạo agent dựng câu trả lời **hai lần** — một lần từ thực thể, rồi một lần nữa từ
    chính câu trả lời ấy để nới rộng ra. Lượt thứ hai đọc theo tên trường của tầng trình bày,
    không theo tên của thực thể, nên thứ vừa chọn rơi mất trên đường về: agent tạo ra kèm một
    model trả lời là nó **không có** model nào, và màn hình tin cho tới lần đọc lại sau đó.
    """
    async with _client() as c:
        machine = await link_machine(c, f"pb-{uuid4().hex[:8]}@example.com", hostname="box")
        await _declares(machine.workplace_id, _CLAUDE_LIKE)

        made = await _agent(
            c, machine, "Marin", runtime_options={"model": "opus", "thinking_level": "high"}
        )
        assert made.status_code == 201, made.text
        assert made.json()["runtime_options"] == {"model": "opus", "thinking_level": "high"}
