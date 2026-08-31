"""Máy tự hỏi trước khi xoá thư mục của chính nó (T134, FR-021, FR-021a).

Không có tin báo nào đi xuống. Server không bao giờ nói *đầu việc này khép rồi, buông thư mục
đi* — một câu như thế có thể được gửi lúc máy đang tắt, và cái máy lỡ mất nó sẽ giữ thư mục ấy
mãi mãi. Nên chiều đi ngược lại: máy hỏi, theo nhịp của nó, về đúng những thư mục nó đang có.
Một câu hỏi bị hỏi muộn thì vẫn được trả lời.

Điểm phải giữ cho đúng ở cửa này là **cái tên không có trong câu trả lời**. Vắng mặt không phải
lỗi, cũng không phải một lời từ chối: nó là câu *server không kể tên được đầu việc này* — đã
xoá, chưa từng ghi, hoặc của workspace bên cạnh. Vòng quét có một cái đồng hồ dài hơn hẳn dành
riêng cho ca ấy (FR-021a). Đó cũng là lý do cửa này không cần nhánh 404 nào để giữ Điều I: đầu
việc của người bên cạnh và đầu việc chưa bao giờ tồn tại cho ra cùng một sự im lặng.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import update

from armarius.domain.entities.task import TaskStatus
from armarius.infrastructure.daemon.housekeeping import MAX_TASKS_PER_ASK
from armarius.infrastructure.database.engine import get_sessionmaker
from armarius.infrastructure.database.models import TaskModel
from armarius.main import app
from armarius.shared.clock import utcnow
from tests.support.machines import auth, link_machine
from tests.support.work import a_project, a_task

pytestmark = pytest.mark.anyio


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")



def _stamp(text: str) -> datetime:
    return datetime.fromisoformat(text)


async def _ask(c: AsyncClient, token: str, names: list[str]) -> dict[str, dict]:
    """Một lượt hỏi, trả về đúng thứ vòng quét đọc: tra theo tên."""
    answered = await c.post(
        "/daemon/tasks/states", json={"task_ids": names}, headers=auth(token)
    )
    assert answered.status_code == 200, answered.text
    return {row["task_id"]: row for row in answered.json()["tasks"]}


async def _close(task_id: UUID, *, status: TaskStatus, quiet_for: timedelta) -> None:
    """Khép một đầu việc lại, và lùi cả hàng về quá khứ chứ không chỉ một cột.

    Dựng một hàng có thật: đầu việc được tạo ra **trước** lúc nó khép lại. Chỉ lùi mỗi
    `updated_at` sẽ ra một hàng không đời nào tồn tại — sửa trước khi tạo — và một bài kiểm
    dựng trên hàng như thế chỉ đo được cách viết truy vấn, không đo được luật.
    """
    quiet_since = utcnow() - quiet_for
    async with get_sessionmaker()() as session:
        await session.execute(
            update(TaskModel)
            .where(TaskModel.id == task_id)
            .values(
                status=status.value,
                created_at=quiet_since - timedelta(hours=1),
                updated_at=quiet_since,
                completed_at=quiet_since if status is TaskStatus.DONE else None,
            )
        )
        await session.commit()


async def test_an_open_task_holds_its_directory() -> None:
    """Chưa khép thì không có gì để bàn: vòng quét đọc `closed=false` rồi để yên."""
    async with _client() as c:
        machine = await link_machine(c, f"open-{uuid4().hex[:8]}@example.com")
        project_id = await a_project(machine.workspace_id)
        task_id = await a_task(project_id)

        found = await _ask(c, machine.token, [str(task_id)])
        assert found[str(task_id)]["closed"] is False


async def test_a_closed_task_says_how_long_it_has_been_quiet() -> None:
    """Điều kiện xoá có hai vế, và vế thứ hai là một con số — nên nó phải đi ra được."""
    async with _client() as c:
        machine = await link_machine(c, f"closed-{uuid4().hex[:8]}@example.com")
        project_id = await a_project(machine.workspace_id)
        task_id = await a_task(project_id)
        await _close(task_id, status=TaskStatus.DONE, quiet_for=timedelta(days=3))

        row = (await _ask(c, machine.token, [str(task_id)]))[str(task_id)]
        assert row["closed"] is True
        quiet = utcnow() - _stamp(row["last_activity"])
        assert timedelta(days=2, hours=23) < quiet < timedelta(days=3, hours=1), row


async def test_cancelled_counts_as_closed_and_blocked_does_not() -> None:
    """Bốn nghĩa của *khép lại* dễ trượt thành *không chạy nữa* — đúng hai cái được tính."""
    async with _client() as c:
        machine = await link_machine(c, f"kinds-{uuid4().hex[:8]}@example.com")
        project_id = await a_project(machine.workspace_id)

        by_status = {}
        for status in (TaskStatus.CANCELLED, TaskStatus.BLOCKED, TaskStatus.IN_REVIEW):
            task_id = await a_task(project_id)
            await _close(task_id, status=status, quiet_for=timedelta(days=9))
            by_status[status] = str(task_id)

        found = await _ask(c, machine.token, list(by_status.values()))
        assert found[by_status[TaskStatus.CANCELLED]]["closed"] is True
        assert found[by_status[TaskStatus.BLOCKED]]["closed"] is False, (
            "đầu việc đang vướng bị đọc thành đã khép — thư mục của nó sẽ bị xoá "
            "trong khi vẫn còn người quay lại làm tiếp"
        )
        assert found[by_status[TaskStatus.IN_REVIEW]]["closed"] is False


async def test_a_name_the_workspace_cannot_account_for_is_simply_absent() -> None:
    """Vắng mặt là câu trả lời, không phải lỗi (FR-021a)."""
    async with _client() as c:
        machine = await link_machine(c, f"gone-{uuid4().hex[:8]}@example.com")
        project_id = await a_project(machine.workspace_id)
        task_id = await a_task(project_id)
        invented = str(uuid4())

        found = await _ask(c, machine.token, [str(task_id), invented])
        assert str(task_id) in found
        assert invented not in found


async def test_a_task_next_door_reads_exactly_like_one_that_never_existed() -> None:
    """Điều I ở đúng cửa dễ quên nhất: cửa này nhận **một danh sách mã do máy tự khai**."""
    async with _client() as c:
        a = await link_machine(c, f"a-{uuid4().hex[:8]}@example.com", hostname="alpha")
        b = await link_machine(c, f"b-{uuid4().hex[:8]}@example.com", hostname="beta")
        assert a.workspace_id != b.workspace_id

        theirs = await a_task(await a_project(a.workspace_id))
        invented = str(uuid4())

        borrowed = await _ask(c, b.token, [str(theirs)])
        fictional = await _ask(c, b.token, [invented])
        assert borrowed == fictional == {}, (
            f"máy B học được một điều về đầu việc của A: {borrowed}"
        )

        # Và đầu việc của A vẫn trả lời A như thường.
        assert str(theirs) in await _ask(c, a.token, [str(theirs)])


async def test_a_directory_name_that_is_not_a_task_id_does_not_cost_the_whole_sweep() -> None:
    """Tên thư mục là thứ trên đĩa của người ta — có thể là bất cứ cái gì.

    Trả 422 cho cả lô vì một cái tên lạ sẽ dừng hẳn vòng quét, và cái tên lạ ấy chính là thứ
    FR-021a sinh ra để dọn.
    """
    async with _client() as c:
        machine = await link_machine(c, f"junk-{uuid4().hex[:8]}@example.com")
        task_id = await a_task(await a_project(machine.workspace_id))

        found = await _ask(c, machine.token, [str(task_id), "tmp-download", "..", ""])
        assert list(found) == [str(task_id)]


async def test_one_ask_carries_a_bounded_number_of_names() -> None:
    """Trần chống rác, không phải trần cho vòng quét: máy nhiều thư mục thì hỏi nhiều lượt."""
    async with _client() as c:
        machine = await link_machine(c, f"cap-{uuid4().hex[:8]}@example.com")
        too_many = [str(uuid4()) for _ in range(MAX_TASKS_PER_ASK + 1)]

        answered = await c.post(
            "/daemon/tasks/states",
            json={"task_ids": too_many},
            headers=auth(machine.token),
        )
        assert answered.status_code == 422, answered.text

        at_the_line = await c.post(
            "/daemon/tasks/states",
            json={"task_ids": too_many[:MAX_TASKS_PER_ASK]},
            headers=auth(machine.token),
        )
        assert at_the_line.status_code == 200, at_the_line.text


async def test_a_machine_without_a_token_learns_nothing() -> None:
    """Cửa của daemon, nên nó đòi token của một cái máy như mọi cửa khác."""
    async with _client() as c:
        answered = await c.post("/daemon/tasks/states", json={"task_ids": [str(uuid4())]})
        assert answered.status_code == 401, answered.text
