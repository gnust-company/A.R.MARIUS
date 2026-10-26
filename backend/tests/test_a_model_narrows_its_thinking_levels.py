"""Mỗi model nhận một bộ mức suy nghĩ riêng (FR-007k của đặc tả 002, sửa 2026-10-26).

Người chủ thử ngày 2026-10-26 và thấy danh sách model của Claude Code chỉ có ba cái tên ví dụ. Hỏi
thẳng Claude Code thì nó trả đủ danh sách, và lộ thêm một điều: không phải model nào cũng nhận mọi
mức — Opus 4.6 không có `xhigh`, Haiku 4.5 không nhận mức nào. Một danh sách mức chung cho cả chỗ
làm thì cho chọn đúng thứ model ấy không chạy được.

Luật được viết bằng **khoá của lựa chọn**, không bằng tên tool: server đo được mà không biết khoá
nào là model (Điều III). Các bài dưới đây ghi thẳng thứ máy khai vào cột, đúng hình dạng daemon thật
gửi lên, như `test_agent_runtime_options.py` vẫn làm.
"""

from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import update

from armarius.infrastructure.daemon.models import WorkplaceModel
from armarius.infrastructure.database.engine import get_sessionmaker
from armarius.main import app
from tests.support.machines import link_machine

pytestmark = pytest.mark.anyio

_OPUS_5_5 = "claude-opus-5-5"
_OPUS_4_6 = "claude-opus-4-6"
_HAIKU_4_5 = "claude-haiku-4-5-20251001"

_LISTED = [
    {
        "key": "thinking_level",
        "values": ["low", "medium", "high", "xhigh", "max"],
        "source": "tool_declared",
    },
    {
        "key": "model",
        "values": [_OPUS_5_5, _OPUS_4_6, _HAIKU_4_5],
        "source": "tool_listed",
        "labels": {
            _OPUS_5_5: "Opus 5.5",
            _OPUS_4_6: "Opus 4.6",
            _HAIKU_4_5: "Haiku 4.5",
            # Nhãn cho một giá trị không có trong danh sách: dữ liệu từ máy người khác, bỏ đi.
            "claude-ghost": "Ghost",
        },
        "narrows": {
            _OPUS_5_5: {"thinking_level": ["low", "medium", "high", "xhigh", "max"]},
            _OPUS_4_6: {"thinking_level": ["low", "medium", "high", "max"]},
            _HAIKU_4_5: {"thinking_level": []},
            "claude-ghost": {"thinking_level": ["low"]},
        },
    },
]


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def _declares(workplace_id: str, choices: list[dict]) -> None:
    async with get_sessionmaker()() as session:
        await session.execute(
            update(WorkplaceModel)
            .where(WorkplaceModel.id == UUID(workplace_id))
            .values(capabilities={"resumable": True, "choices": choices})
        )
        await session.commit()


async def _machine(c: AsyncClient, choices: list[dict] = _LISTED):
    machine = await link_machine(c, f"narrows-{uuid4().hex[:8]}@example.com")
    await _declares(machine.workplace_id, choices)
    return machine


async def _agent(c: AsyncClient, machine, name: str, options: dict[str, str]):
    return await c.post(
        f"/v1/workspaces/{machine.workspace_id}/mariuses",
        json={"name": name, "workplace_id": machine.workplace_id, "runtime_options": options},
        headers=machine.headers,
    )


async def _offered(c: AsyncClient, machine) -> dict[str, dict]:
    listed = await c.get(
        f"/v1/workspaces/{machine.workspace_id}/workplaces", headers=machine.headers
    )
    assert listed.status_code == 200, listed.text
    return {o["key"]: o for o in listed.json()[0]["options"]}


async def test_the_screen_gets_a_readable_name_and_the_narrowing_for_each_model():
    async with _client() as c:
        machine = await _machine(c)
        model = (await _offered(c, machine))["model"]

        assert model["source"] == "tool_listed"
        assert model["labels"] == {
            _OPUS_5_5: "Opus 5.5",
            _OPUS_4_6: "Opus 4.6",
            _HAIKU_4_5: "Haiku 4.5",
        }
        assert model["narrows"][_OPUS_4_6] == {"thinking_level": ["low", "medium", "high", "max"]}
        assert model["narrows"][_HAIKU_4_5] == {"thinking_level": []}
        assert "claude-ghost" not in model["narrows"], "luật cho giá trị không có thật phải bị bỏ"


async def test_a_narrowing_aimed_at_a_setting_that_does_not_exist_is_dropped():
    choices = [
        _LISTED[0],
        {
            **_LISTED[1],
            "narrows": {_OPUS_5_5: {"service_tier": ["fast"], "thinking_level": ["low"]}},
        },
    ]
    async with _client() as c:
        machine = await _machine(c, choices)
        model = (await _offered(c, machine))["model"]
        assert model["narrows"] == {_OPUS_5_5: {"thinking_level": ["low"]}}


async def test_labels_and_narrowing_that_are_not_the_right_shape_are_ignored_not_fatal():
    """Cột này do một chương trình trên máy người khác viết: hỏng thì bỏ, không sửa, không vỡ."""
    choices = [
        _LISTED[0],
        {
            **_LISTED[1],
            "labels": ["Opus"],
            "narrows": {_OPUS_5_5: "low", _OPUS_4_6: {"thinking_level": "low"}},
        },
    ]
    async with _client() as c:
        machine = await _machine(c, choices)
        model = (await _offered(c, machine))["model"]
        assert model["values"] == [_OPUS_5_5, _OPUS_4_6, _HAIKU_4_5]
        assert model["labels"] == {}
        assert model["narrows"] == {}


async def test_a_listed_model_set_still_takes_a_model_it_did_not_list():
    """Claude Code liệt kê thứ nó bày cho tài khoản này, nhưng vẫn nhận tên model khác."""
    async with _client() as c:
        machine = await _machine(c)
        made = await _agent(c, machine, "Cassia", {"model": "claude-opus-4-1"})
        assert made.status_code == 201, made.text


async def test_a_level_the_chosen_model_does_not_take_is_refused():
    async with _client() as c:
        machine = await _machine(c)
        refused = await _agent(c, machine, "Nona", {"model": _OPUS_4_6, "thinking_level": "xhigh"})
        assert refused.status_code == 422, refused.text
        assert refused.json()["code"] == "placement_option_value_unsupported"
        assert refused.json()["params"] == {"option": "thinking_level", "value": "xhigh"}

        taken = await _agent(c, machine, "Decima", {"model": _OPUS_4_6, "thinking_level": "max"})
        assert taken.status_code == 201, taken.text


async def test_a_model_that_takes_no_level_takes_only_a_blank_one():
    async with _client() as c:
        machine = await _machine(c)
        refused = await _agent(c, machine, "Morta", {"model": _HAIKU_4_5, "thinking_level": "low"})
        assert refused.status_code == 422, refused.text

        blank = await _agent(c, machine, "Tullia", {"model": _HAIKU_4_5, "thinking_level": ""})
        assert blank.status_code == 201, blank.text


async def test_changing_only_the_level_is_measured_against_the_model_already_saved():
    async with _client() as c:
        machine = await _machine(c)
        made = await _agent(c, machine, "Aurel", {"model": _OPUS_4_6})
        assert made.status_code == 201, made.text
        at = f"/v1/workspaces/{machine.workspace_id}/mariuses/{made.json()['id']}"

        refused = await c.patch(
            at, json={"runtime_options": {"thinking_level": "xhigh"}}, headers=machine.headers
        )
        assert refused.status_code == 422, refused.text

        taken = await c.patch(
            at, json={"runtime_options": {"thinking_level": "high"}}, headers=machine.headers
        )
        assert taken.status_code == 200, taken.text
        assert taken.json()["runtime_options"] == {"model": _OPUS_4_6, "thinking_level": "high"}


async def test_changing_only_the_model_does_not_put_the_saved_level_on_trial():
    """Luật *chỉ đo thứ lần này được chọn* (FR-007k): mức đã lưu không bị lôi ra đo lại. Màn
    hình là bên đưa mức về mặc định khi đổi model, và nó gửi cả hai cùng lúc."""
    async with _client() as c:
        machine = await _machine(c)
        made = await _agent(c, machine, "Flavia", {"model": _OPUS_5_5, "thinking_level": "xhigh"})
        assert made.status_code == 201, made.text
        at = f"/v1/workspaces/{machine.workspace_id}/mariuses/{made.json()['id']}"

        moved = await c.patch(
            at, json={"runtime_options": {"model": _HAIKU_4_5}}, headers=machine.headers
        )
        assert moved.status_code == 200, moved.text

        both = await c.patch(
            at,
            json={"runtime_options": {"model": _OPUS_4_6, "thinking_level": ""}},
            headers=machine.headers,
        )
        assert both.status_code == 200, both.text
        assert both.json()["runtime_options"] == {"model": _OPUS_4_6, "thinking_level": ""}
