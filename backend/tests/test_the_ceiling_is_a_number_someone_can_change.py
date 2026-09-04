"""Trần số lượt chạy đồng thời của một cái máy phải **chỉnh được** (FR-008, SC-009).

Trần đã có và đã được thi hành từ trước: cửa nhận việc lấy **số nhỏ hơn** giữa số chỗ trống
daemon báo về và trần server ghi (FR-008d), nên một cái máy báo lạc quan cũng không lấy được
nhiều hơn trần. Thứ chưa có là **cách đổi cái trần ấy**: nó là một cột với mặc định bằng 1 mà
không cửa nào, không màn hình nào ghi vào. Một hằng số thì không phải cái trần chỉnh được mà
FR-008 đòi — nó là cái trần không ai với tới.

Đo lúc chạy trọn quickstart (T129): mọi máy trong cơ sở dữ liệu đều đứng ở 1, nên SC-009
*không lần nào đạt được* — một máy không thể chạy năm lượt cùng lúc khi trần của nó là một.

Bốn điều bài này giữ:

  * người chủ đổi được trần, và đọc lại đúng con số vừa đặt;
  * ngoài khoảng cho phép thì bị từ chối kèm **hai đầu khoảng**, không phải một câu chung;
  * máy của người khác đọc y hệt máy không tồn tại (Điều I);
  * và điều đáng giá nhất: sau khi đổi, **cửa nhận việc giao đúng tới trần mới** — còn hạ
    trần thì không thu hồi thứ đã ra khỏi tay.
"""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from armarius.infrastructure.daemon.workplaces import MAX_CEILING, MIN_CEILING
from armarius.main import app
from tests.support.agents import invite_agent
from tests.support.machines import auth, link_machine
from tests.support.work import a_project, a_task, shelve

pytestmark = pytest.mark.anyio


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def _machine(c: AsyncClient, workspace_id: str, headers: dict) -> dict:
    answered = await c.get(f"/v1/workspaces/{workspace_id}/machines", headers=headers)
    assert answered.status_code == 200, answered.text
    return answered.json()[0]


async def _set(c: AsyncClient, machine, ceiling: int):
    return await c.patch(
        f"/v1/workspaces/{machine.workspace_id}/machines/{machine.machine_id}",
        json={"max_concurrent": ceiling},
        headers=machine.headers,
    )


async def _shelve_some(machine, how_many: int, *, name: str) -> list[str]:
    """`how_many` runs waiting at this machine's workplace, one agent each.

    One agent each because an agent holds one run at a time: three runs behind one agent
    would measure that rule instead of the ceiling.
    """
    project_id = await a_project(machine.workspace_id)
    runs = []
    async with _client() as c:
        for index in range(how_many):
            agent = await invite_agent(
                c,
                machine.workspace_id,
                machine.headers,
                name=f"{name}{index}",
                workplace_id=machine.workplace_id,
            )
            task_id = await a_task(project_id, assigned_to=agent["id"])
            runs.append(str(await shelve(marius_id=agent["id"], task_id=task_id)))
    return runs


async def _ask(c: AsyncClient, machine, *, most: int) -> list[dict]:
    got = await c.post(
        "/daemon/runs/claim",
        json={"workplace_ids": [machine.workplace_id], "max": most},
        headers=auth(machine.token),
    )
    assert got.status_code == 200, got.text
    return got.json()["runs"]


async def test_a_machine_starts_at_one_and_says_so() -> None:
    """Mặc định phải **đọc được**: con số không ai thấy là con số không ai chọn."""
    async with _client() as c:
        machine = await link_machine(c, "ceiling-default@armarius.dev")
        one = await _machine(c, machine.workspace_id, machine.headers)

    assert one["max_concurrent"] == 1, one


async def test_the_patron_moves_the_ceiling_and_reads_it_back() -> None:
    async with _client() as c:
        machine = await link_machine(c, "ceiling-move@armarius.dev")

        changed = await _set(c, machine, 5)
        assert changed.status_code == 200, changed.text
        assert changed.json()["max_concurrent"] == 5

        again = await _machine(c, machine.workspace_id, machine.headers)

    assert again["max_concurrent"] == 5, again


async def test_a_ceiling_outside_the_range_is_refused_with_both_ends() -> None:
    """Hai đầu khoảng đi kèm mã lỗi, để màn hình nói đúng con số server đang giữ."""
    async with _client() as c:
        machine = await link_machine(c, "ceiling-range@armarius.dev")

        for silly in (0, -3, MAX_CEILING + 1):
            refused = await _set(c, machine, silly)
            assert refused.status_code == 400, (silly, refused.text)
            body = refused.json()
            assert body["code"] == "machine_ceiling_out_of_range", body
            assert body["params"] == {"least": str(MIN_CEILING), "most": str(MAX_CEILING)}

        # Và hai đầu khoảng thì nhận.
        for fine in (MIN_CEILING, MAX_CEILING):
            allowed = await _set(c, machine, fine)
            assert allowed.status_code == 200, (fine, allowed.text)
            assert allowed.json()["max_concurrent"] == fine


async def test_another_persons_machine_reads_as_no_such_machine() -> None:
    """Điều I: không-phải-của-mình đọc y hệt không-có, nên là 404 chứ không phải 403."""
    async with _client() as c:
        mine = await link_machine(c, "ceiling-mine@armarius.dev")
        theirs = await link_machine(c, "ceiling-theirs@armarius.dev", hostname="other")

        refused = await c.patch(
            f"/v1/workspaces/{mine.workspace_id}/machines/{theirs.machine_id}",
            json={"max_concurrent": 4},
            headers=mine.headers,
        )
        assert refused.status_code == 404, refused.text
        assert refused.json()["code"] == "machine_not_found"

        # Và cái máy kia không hề bị đụng tới.
        untouched = await _machine(c, theirs.workspace_id, theirs.headers)
        assert untouched["max_concurrent"] == 1, untouched


async def test_the_new_ceiling_is_what_the_claim_hands_out() -> None:
    """Phép đo thật của SC-009: đổi trần rồi xin việc, và nhận được nhiều hơn một."""
    async with _client() as c:
        machine = await link_machine(c, "ceiling-claim@armarius.dev")
        await _shelve_some(machine, 5, name="Hand")

        # Trần cũ: một lượt, dù máy khai còn năm chỗ trống.
        first = await _ask(c, machine, most=5)
        assert len(first) == 1, first

        assert (await _set(c, machine, 5)).status_code == 200
        rest = await _ask(c, machine, most=5)

    # Bốn nữa, cho tròn năm: cái đang giữ vẫn tính vào trần (FR-008d).
    assert len(rest) == 4, rest
    assert len({run["run_id"] for run in first + rest}) == 5


async def test_lowering_the_ceiling_does_not_recall_work_already_out() -> None:
    """Trần được đọc **lúc xin việc**. Hạ nó xuống là ngừng đưa thêm, không phải thu về."""
    async with _client() as c:
        machine = await link_machine(c, "ceiling-lower@armarius.dev")
        await _shelve_some(machine, 4, name="Palm")

        assert (await _set(c, machine, 3)).status_code == 200
        out = await _ask(c, machine, most=3)
        assert len(out) == 3, out

        assert (await _set(c, machine, 1)).status_code == 200
        after = await _ask(c, machine, most=3)
        assert after == [], after

        # Ba lượt đã ra khỏi tay vẫn còn nguyên, và vẫn đọc được bằng token của chúng.
        for run in out:
            still = await c.get(
                f"/v1/runs/{run['run_id']}", headers=machine.headers
            )
            assert still.status_code == 200, still.text
            assert still.json()["status"] in ("queued", "running"), still.json()
