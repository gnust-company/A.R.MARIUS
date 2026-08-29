"""Không phải của mình thì đọc y như không có — trên **mọi** cửa của daemon (T075, Điều I, FR-036).

Hai cái máy, hai workspace, hai người chủ không quen nhau. Máy B cầm token thật của chính nó
— không phải token hỏng, không phải token hết hạn — rồi gõ vào từng cửa `/daemon/*` về đồ của
máy A. Mỗi cửa phải trả lời như thể đồ ấy **không tồn tại**: 404, không phải 403.

**Vì sao 404 chứ không 403.** Một cái 403 nói *có thứ này, nhưng không cho anh xem* — và đó đã
là một câu trả lời về đồ của người khác. Máy B học được rằng có một lượt chạy mang đúng mã ấy,
tức là học được một điều nó không có quyền học. 404 thì không nói gì cả, và đó là điểm của
Điều I.

**Vì sao danh sách cửa lấy từ bản mô tả dịch vụ, không gõ tay.** `test_workspace_scope_sweep`
đã học bài này một lần rồi: danh sách gõ tay kể 4 trên 17 cửa, mười ba cửa còn lại chưa ai
nhìn, và **không bài nào đỏ**. Ở đây phép quét đọc `app.openapi()` rồi khẳng định mọi cửa
`/daemon/*` đều đã được bài này chạm tới — nên một cửa thêm vào tháng sau mà không ai nghĩ tới
chuyện cách ly sẽ làm bài này **đỏ ngay**, chứ không lặng lẽ đi qua.

**Hai loại cửa, hai cách hỏi.** Có cửa mang mã của đồ trên đường dẫn (`/runs/{run_id}/…`) —
hỏi thẳng bằng mã của A. Có cửa không mang mã nào (`claim`, `heartbeat`, `workplaces`,
`events`, `token/renew`) — thứ phải chứng minh ở đó không phải một con số mã lỗi, mà là **đồ
của A không bao giờ đi ra qua tay B**. Cả hai đều là cách ly; gộp chúng vào một khuôn duy nhất
sẽ hoặc bỏ sót loại thứ hai, hoặc đòi loại thứ hai trả 404 cho một câu hỏi hợp lệ.
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from armarius.main import app
from tests.support.agents import invite_agent
from tests.support.machines import auth, link_machine
from tests.support.work import a_project, a_task, shelve

pytestmark = pytest.mark.anyio


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


@dataclass
class Side:
    """Một bên: máy, chỗ làm, agent, và một lượt chạy đang chờ trên kệ."""

    token: str
    workspace_id: str
    workplace_id: str
    marius_id: str
    run_id: UUID
    task_id: UUID

    @property
    def headers(self) -> dict[str, str]:
        return auth(self.token)


async def _side(c: AsyncClient, email: str, *, hostname: str) -> Side:
    """Cả chặng thật: người đăng ký, máy xin vào, người duyệt, máy khai chỗ làm, agent lên máy."""
    machine = await link_machine(c, email, hostname=hostname)
    agent = await invite_agent(
        c,
        machine.workspace_id,
        machine.headers,
        name=hostname,
        workplace_id=machine.workplace_id,
    )
    project_id = await a_project(machine.workspace_id)
    task_id = await a_task(project_id, assigned_to=agent["id"])
    run_id = await shelve(marius_id=agent["id"], task_id=task_id)
    return Side(
        token=machine.token,
        workspace_id=machine.workspace_id,
        workplace_id=machine.workplace_id,
        marius_id=agent["id"],
        run_id=run_id,
        task_id=task_id,
    )


async def _two_sides(c: AsyncClient) -> tuple[Side, Side]:
    a = await _side(c, f"a-{uuid4().hex[:8]}@example.com", hostname="alpha")
    b = await _side(c, f"b-{uuid4().hex[:8]}@example.com", hostname="beta")
    assert a.workspace_id != b.workspace_id
    return a, b


# ── 1. cửa mang mã của đồ trên đường dẫn ──────────────────────────────────────


async def test_a_stranger_cannot_touch_a_run_that_is_not_its_own() -> None:
    """Ba cửa của một lượt chạy, hỏi bằng mã thật của A, bằng token thật của B."""
    async with _client() as c:
        a, b = await _two_sides(c)
        # A cầm việc của mình cho thật — có một lượt chạy sống để mà giấu.
        taken = await c.post(
            "/daemon/runs/claim",
            json={"workplace_ids": [a.workplace_id], "max": 1},
            headers=a.headers,
        )
        assert [r["run_id"] for r in taken.json()["runs"]] == [str(a.run_id)]

        for method, path, body in (
            ("POST", f"/daemon/runs/{a.run_id}/start", {"session": "s-1"}),
            (
                "POST",
                f"/daemon/runs/{a.run_id}/events",
                {"events": [{"seq": 1, "type": "assistant.message", "payload": {}}]},
            ),
            ("POST", f"/daemon/runs/{a.run_id}/finish", {"status": "completed"}),
        ):
            answered = await c.request(method, path, json=body, headers=b.headers)
            assert answered.status_code == 404, (
                f"{path} nói cho người lạ biết lượt chạy này có thật: "
                f"{answered.status_code} {answered.text}"
            )


async def test_a_run_next_door_reads_exactly_like_one_that_was_never_created() -> None:
    """Điều I nói đủ: hai câu trả lời phải **không phân biệt được**.

    Một mã bịa ra và một mã có thật ở workspace bên cạnh phải cho ra cùng một câu — cùng mã
    HTTP và cùng mã lý do. Khác nhau ở bất kỳ đâu là một kênh rò: gõ thử một nghìn mã, cái nào
    trả lời khác đi là cái có thật.
    """
    async with _client() as c:
        a, b = await _two_sides(c)
        invented = uuid4()

        ending = {"status": "completed"}
        real = await c.post(
            f"/daemon/runs/{a.run_id}/finish", json=ending, headers=b.headers
        )
        fictional = await c.post(
            f"/daemon/runs/{invented}/finish", json=ending, headers=b.headers
        )

        assert real.status_code == fictional.status_code == 404
        assert real.json().get("code") == fictional.json().get("code"), (
            "lượt chạy có thật của người khác trả lời khác lượt chạy không tồn tại — "
            f"{real.json()} vs {fictional.json()}"
        )


# ── 2. cửa không mang mã nào: đồ của A không đi ra qua tay B ──────────────────


async def test_work_waiting_next_door_is_never_handed_to_this_machine() -> None:
    """Cửa nhận việc không có gì để trả 404 — câu hỏi của B hợp lệ, chỉ là kệ của B rỗng."""
    async with _client() as c:
        a, b = await _two_sides(c)

        # B xin, và xin cả bằng mã chỗ làm của A — đúng thứ một cái máy tò mò sẽ thử.
        tried = ([b.workplace_id], [a.workplace_id], [a.workplace_id, b.workplace_id])
        for workplace_ids in tried:
            answered = await c.post(
                "/daemon/runs/claim",
                json={"workplace_ids": workplace_ids, "max": 10},
                headers=b.headers,
            )
            assert answered.status_code == 200, answered.text
            handed = {r["run_id"] for r in answered.json()["runs"]}
            assert str(a.run_id) not in handed, (
                f"xin bằng {workplace_ids} lấy được việc của workspace bên cạnh: {handed}"
            )

        # Và việc của A vẫn nằm nguyên trên kệ cho A.
        mine = await c.post(
            "/daemon/runs/claim",
            json={"workplace_ids": [a.workplace_id], "max": 1},
            headers=a.headers,
        )
        assert [r["run_id"] for r in mine.json()["runs"]] == [str(a.run_id)]


async def test_naming_another_machines_workplace_finds_nothing_rather_than_refusing() -> None:
    """Mã chỗ làm của người khác đọc y như một mã bịa: không có, chứ không phải không được."""
    async with _client() as c:
        a, b = await _two_sides(c)

        borrowed = await c.post(
            "/daemon/runs/claim",
            json={"workplace_ids": [a.workplace_id], "max": 5},
            headers=b.headers,
        )
        invented = await c.post(
            "/daemon/runs/claim",
            json={"workplace_ids": [str(uuid4())], "max": 5},
            headers=b.headers,
        )
        assert borrowed.status_code == invented.status_code == 200
        assert borrowed.json()["runs"] == invented.json()["runs"] == []


async def test_a_machine_only_ever_hears_about_its_own_workplaces() -> None:
    """Khai chỗ làm và báo nhịp: câu trả lời không được mang một mảnh nào của máy bên cạnh."""
    async with _client() as c:
        a, b = await _two_sides(c)

        synced = await c.put(
            "/daemon/workplaces",
            json={
                "workplaces": [
                    {
                        "cli_kind": "claude_code",
                        "cli_version": "1.0.0",
                        "protocol_family": "one_shot",
                        "capabilities": {"resumable": True},
                    }
                ],
                "symlink_capable": True,
            },
            headers=b.headers,
        )
        assert synced.status_code == 200, synced.text
        assert a.workplace_id not in synced.text, "máy B nghe thấy chỗ làm của máy A"

        beat = await c.post(
            "/daemon/heartbeat",
            json={"free_slots": 4, "running": []},
            headers=b.headers,
        )
        assert beat.status_code == 200, beat.text
        assert str(a.run_id) not in beat.text, "nhịp của máy B nhắc tới lượt chạy của máy A"


async def test_a_beat_claiming_somebody_elses_run_tells_nothing_and_costs_nothing() -> None:
    """Nhịp **nhận** một danh sách mã từ phía máy — chỗ dễ lọt nhất trong cả nhóm.

    Máy B báo nó đang chạy lượt chạy của A. Hai thứ phải đúng cùng lúc, và chúng khác nhau:

      * **A không mất gì** — lượt chạy của A vẫn của A, vẫn báo bắt đầu được. Một cú đối chiếu
        không lọc theo máy sẽ đọc lời khai của B thành sự thật rồi thu việc của A về.
      * **B không học được gì** — câu trả lời cho một mã có thật của người khác phải **giống hệt**
        câu trả lời cho một mã bịa. Ở đây cả hai đều ra *bỏ nó đi*, và đó là câu đúng: nó nói về
        thứ **B** đang giữ, không nói về thứ có tồn tại hay không (Điều I).
    """
    async with _client() as c:
        a, b = await _two_sides(c)
        taken = await c.post(
            "/daemon/runs/claim",
            json={"workplace_ids": [a.workplace_id], "max": 1},
            headers=a.headers,
        )
        assert taken.json()["runs"], taken.text

        invented = uuid4()
        borrowed = await c.post(
            "/daemon/heartbeat",
            json={"free_slots": 1, "running": [str(a.run_id)]},
            headers=b.headers,
        )
        fictional = await c.post(
            "/daemon/heartbeat",
            json={"free_slots": 1, "running": [str(invented)]},
            headers=b.headers,
        )
        assert borrowed.status_code == fictional.status_code == 200

        # Cùng một câu, chỉ khác đúng cái mã mình vừa tự khai — không một chi tiết nào khác.
        assert borrowed.json() == {**fictional.json(), "cancel": [str(a.run_id)]}, (
            "mã có thật của người khác cho ra câu trả lời khác mã bịa: "
            f"{borrowed.json()} vs {fictional.json()}"
        )

        # Và lời khai của B không đụng được vào việc của A.
        started = await c.post(
            f"/daemon/runs/{a.run_id}/start", json={"session": "s-1"}, headers=a.headers
        )
        assert started.status_code == 200, started.text


# ── 3. lưới: không cửa nào của daemon nằm ngoài bài này ───────────────────────


#: Những cửa mở cho một cái máy **chưa** có danh tính — chặng xin vào. Cách ly không áp
#: được ở đây vì chưa có ai để mà cách ly, và đó chính là việc của chúng.
_BEFORE_THERE_IS_A_MACHINE = {"/daemon/link/start", "/daemon/link/poll"}

#: Cửa đã có bài riêng ở nơi khác, ghi ra để lưới dưới đây không đòi làm lại.
_COVERED_ELSEWHERE = {
    # Đổi token là đổi *của chính mình*: không nhận mã của ai, không trả về gì của ai
    # (`test_daemon_enrollment`).
    "/daemon/token/renew",
    # Đường đẩy chỉ mang một cú hích, không mang dữ liệu (`test_the_push_road_is_only_a_nudge`).
    "/daemon/events",
}

#: Cửa bài này gõ thẳng vào, ghi bằng đúng khuôn đường dẫn trong bản mô tả dịch vụ.
_TOUCHED_HERE = {
    "/daemon/workplaces",
    "/daemon/heartbeat",
    "/daemon/runs/claim",
    "/daemon/runs/{run_id}/start",
    "/daemon/runs/{run_id}/events",
    "/daemon/runs/{run_id}/finish",
}


def test_every_daemon_door_is_accounted_for() -> None:
    """Cửa thêm vào mà quên nghĩ tới cách ly thì bài này đỏ, không im lặng.

    Danh sách đọc từ bản mô tả dịch vụ của chính ứng dụng, nên nó luôn là danh sách **hiện
    tại** — không phải danh sách ai đó nhớ cập nhật.
    """
    doors = {p for p in app.openapi()["paths"] if p.startswith("/daemon")}
    assert doors, "không đọc được cửa nào — hỏng phép quét, không phải hết cửa"

    accounted = _BEFORE_THERE_IS_A_MACHINE | _COVERED_ELSEWHERE | _TOUCHED_HERE
    forgotten = sorted(doors - accounted)
    assert not forgotten, (
        "có cửa `/daemon/*` chưa ai hỏi chuyện cách ly: " + ", ".join(forgotten)
    )
    stale = sorted(accounted - doors)
    assert not stale, (
        "bài này còn kể tên cửa không còn tồn tại — sửa danh sách: " + ", ".join(stale)
    )
