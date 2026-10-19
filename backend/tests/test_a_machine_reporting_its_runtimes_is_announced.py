"""Máy báo runtime thì nói ra trên kênh không gian làm việc (spec 003 FR-120, FR-121, FR-125).

Bước *nối máy* có ba phần — cài, nối, chạy — và phần *chạy* chỉ xong khi máy thật sự báo các
runtime của nó lên. Duyệt máy thôi thì chưa: lúc ấy máy mới có giấy tờ. Cửa sổ onboarding đang
đợi không được hỏi vòng để biết điều đó (Hiến pháp Điều IV), nên tin phải được **đẩy** tới.

Ba điều bài này giữ:

  1. Một lần đồng bộ có runtime phát đúng một tin, trên đúng kênh của không gian làm việc ấy.
  2. Lần báo `stopping` cũng phát: danh sách runtime đang mở phải mất dòng vừa đóng.
  3. Tin là **tín hiệu**, không phải trạng thái: không danh sách nào đi kèm.
"""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from armarius.infrastructure.database.engine import init_db
from armarius.infrastructure.events.workspace_trace import EVENT_WORKPLACES_REPORTED
from armarius.main import app
from tests.support.machines import auth, link_machine, link_machine_to

pytestmark = pytest.mark.anyio


@pytest.fixture(autouse=True)
async def _bootstrap():
    await init_db()
    yield


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


def _reported(workspace_id: str) -> list:
    bus = app.state.container.control_bus
    return [
        e for e in bus.backlog(f"ws:{workspace_id}") if e.type == EVENT_WORKPLACES_REPORTED
    ]


async def test_a_machine_reporting_its_runtimes_is_announced_once_with_nothing_but_the_workspace(
) -> None:
    async with _client() as c:
        machine = await link_machine(c, "runtimes-announced@armarius.dev")

        heard = _reported(machine.workspace_id)
        assert len(heard) == 1, heard
        assert heard[0].data == {"workspace_id": machine.workspace_id}, heard[0].data


async def test_a_machine_stopping_is_announced_too() -> None:
    async with _client() as c:
        machine = await link_machine(c, "stopping-announced@armarius.dev")

        stopped = await c.put(
            "/daemon/workplaces",
            json={"workplaces": [], "stopping": True},
            headers=auth(machine.token),
        )
        assert stopped.status_code == 200, stopped.text

        assert len(_reported(machine.workspace_id)) == 2


async def test_another_workspace_hears_nothing() -> None:
    async with _client() as c:
        machine = await link_machine(c, "own-channel@armarius.dev")
        made = await c.post(
            "/v1/workspaces", headers=machine.headers, json={"name": "Xưởng im lặng"}
        )
        quiet = made.json()["id"]

        await link_machine_to(c, machine.headers, machine.workspace_id, hostname="may-hai")

        assert _reported(quiet) == []
        assert len(_reported(machine.workspace_id)) == 2
