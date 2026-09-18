"""Địa chỉ phê duyệt máy phải là địa chỉ **của nơi triển khai** (FR-001c).

Không phải địa chỉ của một cái máy tính nào đó.

*Người chủ chốt 2026-09-18: "tôi muốn là phải work theo kiểu ip:port vì sắp tới tôi deploy nội bộ
là deploy ở 1 web app và các người dùng khác sẽ vào đó để dùng".*

Trước bài này, địa chỉ ấy là một hằng số: `http://localhost:3000`, mặc định trong mã, và **không
chỗ nào trong compose từng đặt nó**. Nên một cái máy nối vào bản triển khai ở `10.0.0.5:3000` được
bảo đi phê duyệt ở *localhost của chính nó* — trên máy người khác thì địa chỉ ấy hoặc không có gì,
hoặc là một sản phẩm khác. Lỗi này không hiện ra trên máy người phát triển, vì ở đó localhost
tình cờ đúng.

Chỗ đúng để lấy địa chỉ là **chính yêu cầu daemon vừa gọi**: người dùng đã gõ nó vào
`armarius-daemon login -server …` và nó tới được server này, nên nó là địa chỉ **chắc chắn dùng
được** — còn trang web thì nằm cùng origin ấy, vì proxy đặt `/daemon` cạnh giao diện.
"""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from armarius.infrastructure.database.engine import init_db
from armarius.main import app
from armarius.shared.config import settings

pytestmark = pytest.mark.anyio


@pytest.fixture(autouse=True)
async def _bootstrap():
    await init_db()
    yield


def _client(base: str = "http://test") -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url=base)


async def _start(c: AsyncClient, headers: dict[str, str] | None = None) -> dict:
    r = await c.post(
        "/daemon/link/start",
        json={"platform": "linux/amd64", "daemon_version": "0.1.0", "hostname": "may-cua-toi"},
        headers=headers or {},
    )
    assert r.status_code == 200, r.text
    return r.json()


async def test_the_address_is_the_one_the_machine_reached_us_at() -> None:
    """Gõ `ip:port` vào `login` thì địa chỉ phê duyệt cũng là `ip:port` ấy."""
    async with _client("http://10.0.0.5:3000") as c:
        started = await _start(c)
    assert started["verify_url"].startswith("http://10.0.0.5:3000/link?code="), started
    assert started["code"] in started["verify_url"]


async def test_localhost_is_no_longer_baked_in() -> None:
    """Chốt cho đúng lỗi đã có: không bản triển khai nào bị trả về localhost nữa."""
    async with _client("http://192.168.1.50:3000") as c:
        started = await _start(c)
    assert "localhost" not in started["verify_url"], started["verify_url"]


async def test_a_proxy_in_front_is_honoured_both_ways() -> None:
    """Sau một proxy có TLS, địa chỉ trả về phải là `https` và mang tên miền người dùng gõ."""
    async with _client("http://backend:8000") as c:
        started = await _start(
            c,
            {"host": "armarius.noi-bo.vn", "x-forwarded-proto": "https"},
        )
    assert started["verify_url"].startswith("https://armarius.noi-bo.vn/link?code="), started


async def test_a_chain_of_proxies_uses_the_first_scheme() -> None:
    """`x-forwarded-proto: https, http` là một chuỗi — hop đầu mới là thứ browser đã nói."""
    async with _client("http://backend:8000") as c:
        started = await _start(
            c, {"host": "armarius.noi-bo.vn", "x-forwarded-proto": "https, http"}
        )
    assert started["verify_url"].startswith("https://"), started["verify_url"]


async def test_a_configured_address_still_wins() -> None:
    """Trang web ở origin khác hẳn thì người vận hành vẫn khai đè được."""
    settings.web_base_url = "https://ui.armarius.example/"
    try:
        async with _client("http://10.0.0.5:3000") as c:
            started = await _start(c)
    finally:
        settings.web_base_url = ""
    assert started["verify_url"].startswith("https://ui.armarius.example/link?code="), started
    # Dấu gạch thừa ở cuối không được sinh ra `//link`.
    assert "//link" not in started["verify_url"].removeprefix("https://"), started["verify_url"]
