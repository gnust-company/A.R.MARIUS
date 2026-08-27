"""Màn hình Máy đọc ở đâu ra (T069, FR-003, FR-007a, FR-033).

Cho tới đây, người chủ nối một cái máy vào rồi **không có cửa nào để nhìn lại nó**. Cửa duy
nhất liệt kê chỗ làm là cửa của biểu mẫu thêm agent, và nó cố ý chỉ kể chỗ làm **sẵn sàng**
— đúng cho việc chọn, sai hẳn cho việc nhìn: thứ người ta cần thấy nhất là cái chỗ làm vừa
**hỏng**, và ai đang mắc kẹt ở đó.

Ba điều bài này giữ:

  * CLI bị gỡ thì hàng **không biến mất**, nó đỏ lên và vẫn giữ nguyên agent (FR-033, FR-007).
  * Máy còn sống hay không quyết bằng **đúng cái luật** quyết agent còn online hay không —
    hai luật thì sẽ có lúc màn hình nói máy tắt trong khi agent vẫn tính là đang chạy, mà
    hai câu trả lời lệch nhau còn tệ hơn cả hai câu sai.
  * Workspace của người khác đọc y hệt workspace không tồn tại (Điều I).
"""

from __future__ import annotations

from datetime import timedelta
from uuid import UUID

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import update

from armarius.infrastructure.daemon.models import MachineModel, WorkplaceModel
from armarius.infrastructure.daemon.workplaces import REASON_CLI_REMOVED
from armarius.infrastructure.database.engine import get_sessionmaker
from armarius.main import app
from armarius.shared.clock import utcnow
from tests.support.agents import invite_agent
from tests.support.machines import auth, link_machine

pytestmark = pytest.mark.anyio


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def _machines(c: AsyncClient, workspace_id: str, headers: dict) -> list[dict]:
    answered = await c.get(f"/v1/workspaces/{workspace_id}/machines", headers=headers)
    assert answered.status_code == 200, answered.text
    return answered.json()


async def _beat(machine_id: UUID, *, ago: timedelta) -> None:
    async with get_sessionmaker()() as session:
        await session.execute(
            update(MachineModel)
            .where(MachineModel.id == machine_id)
            .values(last_heartbeat_at=utcnow() - ago)
        )
        await session.commit()


async def _uninstall_the_cli(machine_id: UUID) -> None:
    """What a sync reports when the binary is gone: the row stays, and turns not ready."""
    async with get_sessionmaker()() as session:
        await session.execute(
            update(WorkplaceModel)
            .where(WorkplaceModel.machine_id == machine_id)
            .values(ready=False, not_ready_reason=REASON_CLI_REMOVED)
        )
        await session.commit()


async def test_a_linked_machine_shows_what_it_can_run_and_who_lives_there() -> None:
    async with _client() as c:
        machine = await link_machine(c, "screen@armarius.dev", hostname="thinkpad")
        agent = await invite_agent(
            c,
            machine.workspace_id,
            machine.headers,
            name="Marin",
            workplace_id=machine.workplace_id,
        )
        await _beat(machine.machine_id, ago=timedelta(seconds=1))

        listed = await _machines(c, machine.workspace_id, machine.headers)

    assert len(listed) == 1, listed
    one = listed[0]
    assert one["display_name"] == "thinkpad", one
    assert one["platform"] == "linux"
    assert one["reachable"] is True
    assert len(one["workplaces"]) == 1
    place = one["workplaces"][0]
    assert place["cli_kind"] == "claude_code"
    assert place["cli_version"] == "1.0.0"
    assert place["ready"] is True
    assert place["not_ready_reason"] is None
    assert [a["name"] for a in place["agents"]] == ["Marin"]
    assert place["agents"][0]["id"] == agent["id"]


async def test_a_cli_that_was_uninstalled_turns_red_and_keeps_its_agents() -> None:
    """FR-033 nói rõ: chỗ làm mất CLI thì **không xoá**, vì agent vẫn buộc vào đó (FR-007).

    Và đây mới là lúc màn hình đáng giá nhất — người ta mở nó ra chính vì có gì đó hỏng, nên
    câu phải trả lời là *ai đang mắc kẹt ở đây*, chứ không phải một danh sách rỗng.
    """
    async with _client() as c:
        machine = await link_machine(c, "removed@armarius.dev", hostname="thinkpad")
        await invite_agent(
            c,
            machine.workspace_id,
            machine.headers,
            name="Marin",
            workplace_id=machine.workplace_id,
        )
        await _uninstall_the_cli(machine.machine_id)

        listed = await _machines(c, machine.workspace_id, machine.headers)

    place = listed[0]["workplaces"][0]
    assert place["ready"] is False
    assert place["not_ready_reason"] == REASON_CLI_REMOVED
    assert [a["name"] for a in place["agents"]] == ["Marin"], (
        "chỗ làm hỏng mà không kể ai đang mắc kẹt ở đó thì màn hình không trả lời được "
        "câu người ta mở nó ra để hỏi"
    )


async def test_a_machine_that_stopped_beating_is_not_reachable() -> None:
    async with _client() as c:
        machine = await link_machine(c, "quiet@armarius.dev", hostname="thinkpad")
        await _beat(machine.machine_id, ago=timedelta(hours=1))

        listed = await _machines(c, machine.workspace_id, machine.headers)

    assert listed[0]["reachable"] is False, listed


async def test_the_screen_and_the_liveness_verdict_never_disagree() -> None:
    """Một luật, đọc từ hai phía. Đây là bài kiểm về **cùng một con số**, không phải về hai.

    Nếu màn hình dựng lấy ngưỡng riêng thì sẽ tới ngày một cái máy hiện *đang chạy* trong
    khi mọi agent trên nó đã bị tuyên ngoại tuyến — hoặc ngược lại. Người đọc hai câu trái
    nhau thì không tin câu nào.
    """
    from armarius.shared.config import settings

    async with _client() as c:
        machine = await link_machine(c, "agree@armarius.dev", hostname="thinkpad")
        agent = await invite_agent(
            c,
            machine.workspace_id,
            machine.headers,
            name="Marin",
            workplace_id=machine.workplace_id,
        )
        # Đúng bên kia ranh giới mà luật liveness dùng, không phải một con số bịa ra ở đây.
        await _beat(
            machine.machine_id,
            ago=timedelta(seconds=settings.machine_unreachable_after_seconds + 5),
        )

        listed = await _machines(c, machine.workspace_id, machine.headers)

    # Đọc thẳng cái probe chứ không đọc cột `liveness` đã lưu: cột ấy là **kết luận cũ** do
    # vòng quét ghi lại, còn thứ phải khớp với màn hình là **luật**.
    from armarius.infrastructure.daemon.liveness import DaemonLivenessProbe
    from armarius.infrastructure.persistence.unit_of_work import make_uow

    async with make_uow() as uow:
        marin = await uow.mariuses.get(UUID(agent["id"]))
    can_work = await DaemonLivenessProbe(make_uow).probe(marin)

    assert listed[0]["reachable"] is False
    assert can_work is False, "màn hình nói máy đã tắt mà bộ máy vẫn tính agent còn làm được"



async def test_the_last_beat_says_which_moment_it_is() -> None:
    """Cùng họ lỗi với hạn giữ ở T067, mặt thứ hai — lần này người đọc là trình duyệt.

    Một chuỗi ISO không kèm offset thì JavaScript đọc thành **giờ địa phương**, nên cùng một
    nhịp tim sẽ hiện lệch đúng bằng múi giờ của người xem. Không báo lỗi, không ai thấy sai:
    chỉ là "nhịp gần nhất" nói một con số khác sự thật ở mọi máy không chạy giờ UTC.
    """
    from datetime import datetime

    async with _client() as c:
        machine = await link_machine(c, "beat-tz@armarius.dev", hostname="thinkpad")
        await _beat(machine.machine_id, ago=timedelta(seconds=5))

        listed = await _machines(c, machine.workspace_id, machine.headers)

    said = listed[0]["last_heartbeat_at"]
    assert said is not None
    assert datetime.fromisoformat(said).tzinfo is not None, (
        f"nhịp gần nhất đi ra dây mà không nói mình ở múi giờ nào: {said}"
    )


async def test_another_persons_machines_read_as_no_workspace_at_all() -> None:
    async with _client() as c:
        mine = await link_machine(c, "mine-m@armarius.dev", hostname="mine")
        theirs = await link_machine(c, "theirs-m@armarius.dev", hostname="theirs")

        refused = await c.get(
            f"/v1/workspaces/{theirs.workspace_id}/machines", headers=mine.headers
        )

    assert refused.status_code == 404, refused.text


async def test_a_workspace_with_no_machines_answers_with_a_list_not_a_refusal() -> None:
    async with _client() as c:
        registered = await c.post(
            "/auth/register",
            json={
                "email": "nomachines@armarius.dev",
                "full_name": "Patron",
                "password": "password1234",
            },
        )
        person = auth(registered.json()["tokens"]["access_token"])
        workspace_id = (await c.get("/v1/workspaces", headers=person)).json()[0]["id"]

        listed = await _machines(c, workspace_id, person)

    assert listed == []
