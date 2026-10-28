"""Máy nói ra khi daemon của nó không tự cập nhật được (FR-008n của đặc tả 002, sửa 2026-10-28).

Máy của người chủ cài daemon bằng `sudo` vào `/usr/local/bin`: daemon chạy bằng tài khoản thường nên
không ghi đè được chính nó, và ba lần hỏi bản mới đều hỏng ở bước tra tên miền. Mọi thứ ấy chỉ nằm
trong log. Daemon giờ gửi một **mã** theo nhịp tim, server giữ lại, và màn Máy dựng câu từ mã ấy.
"""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from armarius.infrastructure.database.engine import init_db
from armarius.main import app
from tests.support.machines import auth, link_machine


@pytest.fixture(autouse=True)
async def _bootstrap():
    await init_db()
    yield


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def _beat(c: AsyncClient, machine, **extra):
    return await c.post(
        "/daemon/heartbeat",
        headers=auth(machine.token),
        json={"free_slots": 1, "running": [], **extra},
    )


async def _shown(c: AsyncClient, machine) -> dict:
    listed = await c.get(f"/v1/workspaces/{machine.workspace_id}/machines", headers=machine.headers)
    assert listed.status_code == 200, listed.text
    return next(m for m in listed.json() if m["id"] == str(machine.machine_id))


async def test_a_machine_that_cannot_update_itself_says_why_on_the_machines_screen():
    async with _client() as c:
        machine = await link_machine(c, "cannot-update@armarius.dev")

        beat = await _beat(c, machine, update_problem="install_dir_not_writable")
        assert beat.status_code == 200, beat.text
        assert (await _shown(c, machine))["update_problem"] == "install_dir_not_writable"


async def test_a_beat_that_says_nothing_wrong_clears_what_was_said_before():
    """Một lần thử sau thành công thì daemon thôi gửi mã; màn hình phải thôi cảnh báo theo."""
    async with _client() as c:
        machine = await link_machine(c, "update-recovered@armarius.dev")
        await _beat(c, machine, update_problem="release_unreachable")

        quiet = await _beat(c, machine)
        assert quiet.status_code == 200, quiet.text
        assert (await _shown(c, machine))["update_problem"] is None


async def test_a_daemon_from_before_this_says_nothing_and_the_screen_says_nothing():
    async with _client() as c:
        machine = await link_machine(c, "older-daemon@armarius.dev")
        assert (await _shown(c, machine))["update_problem"] is None


async def test_what_rides_the_beat_is_a_code_not_a_sentence():
    """Hiến pháp VII: câu do màn hình dựng theo ngôn ngữ người đọc, nên thứ đi lên là mã."""
    async with _client() as c:
        machine = await link_machine(c, "update-sentence@armarius.dev")
        refused = await _beat(c, machine, update_problem="Permission denied on /usr/local/bin")
        assert refused.status_code == 422, refused.text


async def test_the_version_on_the_machines_screen_follows_the_daemon_after_it_updates_itself():
    """Daemon tự thay chính nó, nên phiên bản khai lúc nối máy cũ đi ngay lần cập nhật đầu."""
    async with _client() as c:
        machine = await link_machine(c, "version-follows@armarius.dev")
        before = (await _shown(c, machine))["daemon_version"]

        await _beat(c, machine, daemon_version="0.2.91")
        assert (await _shown(c, machine))["daemon_version"] == "0.2.91", before

        # Daemon cũ không gửi phiên bản: giữ nguyên thứ đang có, không xoá trắng.
        await _beat(c, machine)
        assert (await _shown(c, machine))["daemon_version"] == "0.2.91"
