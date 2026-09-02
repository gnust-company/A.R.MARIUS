"""Ba cửa nối máy phải có giá khi bị gõ (T126a, FR-001, RFC 8628 §5.2).

Mã nối dài tám ký tự trên bảng ba mươi hai, sống mười phút, dùng một lần. Không con số nào
trong tệp này làm việc đoán mò khó hơn, và cũng không nhắm tới điều đó — cái đếm mua thứ
khác: người lạ không được sai khiến server làm việc miễn phí, và một máy không được hỏi
nhanh hơn nhịp chính server phát cho nó.

Chia làm ba tầng, mỗi tầng đo một thứ riêng và tầng nào cũng có bài đối chứng:

  1. **Bản thân cái đếm** — thuần, không I/O. Cái đếm sai thì mọi thứ dựng trên nó đều sai
     theo, và sai kiểu im lặng.
  2. **Ba hạn mức trước ba cửa** — vẫn thuần: chỉ *lần trượt* mới tính tiền, và dấu gạch
     nối không mua được suất mới.
  3. **Chính ba cửa ấy, chạy qua app thật** — nối dây sai thì hỏng ở đây chứ không hỏng ở
     máy thật đầu tiên.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from httpx import ASGITransport, AsyncClient

from armarius.infrastructure.daemon.link_guard import LinkDoorGuard
from armarius.infrastructure.security.rate_limit import Allowance, FixedWindow
from armarius.main import app
from armarius.shared.clock import utcnow
from armarius.shared.errors import TooManyRequests

pytestmark = pytest.mark.anyio


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


class _Hand:
    """Đồng hồ quay tay — cửa sổ một phút mà ngồi đợi thật thì thành bài bị bỏ qua."""

    def __init__(self, start: datetime | None = None) -> None:
        self.now = start or utcnow()

    def __call__(self) -> datetime:
        return self.now

    def forward(self, seconds: float) -> None:
        self.now += timedelta(seconds=seconds)


async def _register(c: AsyncClient, email: str) -> tuple[dict[str, str], str]:
    r = await c.post(
        "/auth/register",
        json={"email": email, "full_name": "Patron", "password": "password1234"},
    )
    assert r.status_code == 201, r.text
    headers = {"Authorization": f"Bearer {r.json()['tokens']['access_token']}"}
    workspaces = await c.get("/v1/workspaces", headers=headers)
    return headers, workspaces.json()[0]["id"]


async def _a_waiting_code(c: AsyncClient, hostname: str = "thinkpad") -> str:
    started = await c.post(
        "/daemon/link/start",
        json={"platform": "linux", "daemon_version": "0.1.0", "hostname": hostname},
    )
    assert started.status_code == 200, started.text
    return started.json()["code"]


# ── 1. cái đếm ────────────────────────────────────────────────────────────────


def test_one_key_passes_exactly_as_often_as_its_allowance() -> None:
    hand = _Hand()
    window = FixedWindow(
        Allowance(calls=3, per=timedelta(minutes=1)), keys_kept=8, clock=hand
    )

    assert [window.charge("ai-do") for _ in range(3)] == [0.0, 0.0, 0.0], (
        "Ba lần đầu nằm trong suất thì phải đi lọt cả ba"
    )
    assert window.charge("ai-do") > 0.0, "Lần thứ tư vượt suất mà vẫn lọt"


def test_the_refusal_says_how_long_the_wait_is() -> None:
    hand = _Hand()
    window = FixedWindow(
        Allowance(calls=1, per=timedelta(minutes=1)), keys_kept=8, clock=hand
    )
    window.charge("ai-do")
    hand.forward(20)

    assert window.charge("ai-do") == pytest.approx(40.0, abs=0.5), (
        "Phải đợi nốt phần còn lại của cửa sổ, không phải trọn một cửa sổ mới"
    )


def test_a_refused_call_does_not_extend_the_window() -> None:
    """Lần bị chặn không ghi gì cả — nếu ghi thì ai càng thử lại càng bị khoá lâu."""
    hand = _Hand()
    window = FixedWindow(
        Allowance(calls=1, per=timedelta(minutes=1)), keys_kept=8, clock=hand
    )
    window.charge("ai-do")
    for _ in range(20):
        hand.forward(1)
        assert window.charge("ai-do") > 0.0

    hand.forward(45)
    assert window.charge("ai-do") == 0.0, (
        "Hết cửa sổ tính từ lần ĐẦU thì phải mở lại; hai chục lần thử giữa chừng "
        "không được đẩy mốc đi"
    )


def test_a_full_table_turns_new_keys_away_instead_of_growing() -> None:
    hand = _Hand()
    window = FixedWindow(
        Allowance(calls=5, per=timedelta(minutes=1)), keys_kept=2, clock=hand
    )
    assert window.charge("mot") == 0.0
    assert window.charge("hai") == 0.0

    assert window.charge("ba") > 0.0, "Khoá thứ ba lọt vào một cái bảng chỉ chứa được hai"
    assert window.charge("mot") == 0.0, "Khoá đã ở trong bảng vẫn phải đi được như thường"


def test_a_table_full_of_dead_windows_makes_room() -> None:
    hand = _Hand()
    window = FixedWindow(
        Allowance(calls=5, per=timedelta(minutes=1)), keys_kept=2, clock=hand
    )
    window.charge("mot")
    window.charge("hai")
    hand.forward(61)

    assert window.charge("ba") == 0.0, (
        "Hai cửa sổ kia đã hết hạn, nên bảng còn chỗ chứ không phải còn đầy"
    )


# ── 2. ba hạn mức ─────────────────────────────────────────────────────────────


def test_only_a_miss_costs_a_person_anything() -> None:
    guard = LinkDoorGuard(misses_per_minute=2)
    for _ in range(50):
        guard.before_a_person_asks("ai-do")

    guard.a_person_missed("ai-do")
    guard.a_person_missed("ai-do")
    with pytest.raises(TooManyRequests) as refused:
        guard.before_a_person_asks("ai-do")
    assert refused.value.code == "daemon_link_guessed_too_often"
    assert refused.value.retry_after >= 1, "Lời từ chối phải nói được phải đợi bao lâu"


def test_punctuation_does_not_buy_a_fresh_budget() -> None:
    """`KQ7F-M2XD`, `kq7fm2xd` và `kq7f m2xd` là một mã, nên phải tiêu chung một suất."""
    guard = LinkDoorGuard(code_ttl_seconds=60, poll_interval_seconds=60)  # suất mỗi mã = 2
    guard.before_a_machine_polls("KQ7F-M2XD")
    guard.before_a_machine_polls("kq7fm2xd")

    with pytest.raises(TooManyRequests):
        guard.before_a_machine_polls("kq7f m2xd")


def test_both_budgets_on_the_poll_door_refuse_in_the_same_words() -> None:
    """Nói cho người gọi biết họ đụng hạn mức nào là nói về lưu lượng của người khác."""
    per_code = LinkDoorGuard(code_ttl_seconds=60, poll_interval_seconds=60)
    per_code.before_a_machine_polls("AAAA-BBBB")
    per_code.before_a_machine_polls("AAAA-BBBB")
    with pytest.raises(TooManyRequests) as by_code:
        per_code.before_a_machine_polls("AAAA-BBBB")

    whole_door = LinkDoorGuard(polls_per_minute=1)
    whole_door.before_a_machine_polls("AAAA-BBBB")
    with pytest.raises(TooManyRequests) as by_door:
        whole_door.before_a_machine_polls("CCCC-DDDD")

    assert by_code.value.code == by_door.value.code == "daemon_link_polled_too_often"


# ── 3. ba cửa thật ────────────────────────────────────────────────────────────


async def test_somebody_reading_codes_off_a_list_runs_out_of_asks() -> None:
    async with _client() as c:
        headers, _ = await _register(c, "guesser@acme.dev")
        app.state.container.daemon_link_guard = LinkDoorGuard(misses_per_minute=3)

        for _ in range(3):
            missed = await c.get("/v1/machines/link/ZZZZ-9999", headers=headers)
            assert missed.status_code == 404, missed.text

        stopped = await c.get("/v1/machines/link/ZZZZ-9998", headers=headers)
        assert stopped.status_code == 429, stopped.text
        assert stopped.json()["code"] == "daemon_link_guessed_too_often"
        assert stopped.headers["Retry-After"], (
            "Người đọc câu, máy đọc header — thiếu header thì máy phải đoán"
        )


async def test_a_person_linking_their_own_machines_is_never_slowed_down() -> None:
    """Đối chứng: cùng số lượt gọi, nhưng lượt nào cũng trúng mã thật."""
    async with _client() as c:
        headers, _ = await _register(c, "owner@acme.dev")
        app.state.container.daemon_link_guard = LinkDoorGuard(misses_per_minute=3)

        for i in range(10):
            code = await _a_waiting_code(c, hostname=f"box-{i}")
            found = await c.get(f"/v1/machines/link/{code}", headers=headers)
            assert found.status_code == 200, found.text


async def test_naming_the_wrong_workspace_does_not_count_as_a_guess() -> None:
    """404 vì workspace không phải của mình là chuyện khác, không phải một lần thử mã."""
    async with _client() as c:
        headers, _ = await _register(c, "mine@acme.dev")
        _, theirs = await _register(c, "theirs@acme.dev")
        app.state.container.daemon_link_guard = LinkDoorGuard(misses_per_minute=2)
        code = await _a_waiting_code(c)

        for _ in range(5):
            refused = await c.post(
                f"/v1/machines/link/{code}/approve",
                json={"workspace_id": theirs},
                headers=headers,
            )
            assert refused.status_code == 404, refused.text

        still_open = await c.get(f"/v1/machines/link/{code}", headers=headers)
        assert still_open.status_code == 200, still_open.text


async def test_a_machine_asking_too_fast_is_told_to_wait_not_to_stop() -> None:
    async with _client() as c:
        headers, workspace_id = await _register(c, "patron@acme.dev")
        app.state.container.daemon_link_guard = LinkDoorGuard(
            code_ttl_seconds=60, poll_interval_seconds=60  # suất mỗi mã = 2
        )
        code = await _a_waiting_code(c)

        for _ in range(2):
            waiting = await c.post("/daemon/link/poll", json={"code": code})
            assert waiting.status_code == 202, waiting.text

        slow_down = await c.post("/daemon/link/poll", json={"code": code})
        assert slow_down.status_code == 429, slow_down.text
        assert slow_down.json()["code"] == "daemon_link_polled_too_often"

        # 429 không phải 410: mã vẫn sống, và khi hết hạn mức thì cuộc nối vẫn xong được.
        approved = await c.post(
            f"/v1/machines/link/{code}/approve",
            json={"workspace_id": workspace_id},
            headers=headers,
        )
        assert approved.status_code == 200, approved.text
        app.state.container.daemon_link_guard = LinkDoorGuard()
        issued = await c.post("/daemon/link/poll", json={"code": code})
        assert issued.status_code == 200 and issued.json()["token"], issued.text


async def test_the_whole_poll_door_has_a_ceiling_of_its_own() -> None:
    """Suất theo mã không chặn được dò mã — mỗi lần đoán là một mã mới, một suất mới."""
    async with _client() as c:
        app.state.container.daemon_link_guard = LinkDoorGuard(polls_per_minute=3)

        for i in range(3):
            missed = await c.post("/daemon/link/poll", json={"code": f"ZZZZ-000{i}"})
            assert missed.status_code == 410, missed.text

        stopped = await c.post("/daemon/link/poll", json={"code": "ZZZZ-0009"})
        assert stopped.status_code == 429, stopped.text
        assert int(stopped.headers["Retry-After"]) >= 1
