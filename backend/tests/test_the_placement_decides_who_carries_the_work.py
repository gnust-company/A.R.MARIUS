"""Agent thật đi đường daemon, và Chat với Trưởng dự án đi cùng nó (T048c).

Hai việc một tệp vì chúng là hai nửa của một đợt: cú đổi mặc định làm agent tạo ra đi xuống
máy, và cái chat là luồng cuối cùng chưa chuyển. Chuyển chat trước mà không đổi mặc định thì
cả hai luồng đã dựng xong mà **không lượt chạy nào chọn đường ấy cả**; đổi mặc định trước thì
cái chat gọi `execute` của một đường không có `execute` và nổ ngay từ lượt nói đầu tiên.

Bốn điều được đo:

  * chỗ làm **khai** ai chở việc, và người tạo agent chép lại lời khai ấy — không tầng nghiệp
    vụ nào gọi tên một runtime, kể cả bằng một hằng số mặc định (Hiến pháp III, FR-040e);
  * một lượt nói của Trưởng dự án **xuống được máy**: lượt chạy cấp dự án nằm chờ trên kệ,
    khung chat vẫn *đang nghĩ*, và cửa cũ vẫn từ chối lượt thứ hai (FR-040b);
  * câu trả lời dựng lại từ **thứ máy ghi xuống**, không từ thứ tiến trình này giữ trong tay —
    kể cả khi câu ấy dài quá mức ghi thẳng vào sự kiện (FR-049);
  * và một lượt nói **không ai nhận** thì khép ngay tại chỗ, vì một khung chat kẹt ở *đang
    nghĩ* sau một lượt chạy không ai đến lấy sẽ từ chối mọi câu tiếp theo của người chủ.

Đi qua app thật với container thật, và mọi tin từ máy đều vào bằng cửa daemon thật.
"""

from __future__ import annotations

import asyncio
from datetime import timedelta
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, select, update

from armarius.domain.entities.leader_chat import ChatState
from armarius.domain.entities.placement import PLACEMENT_CARRIES_NOTHING, Placement
from armarius.domain.entities.run import RunStatus
from armarius.infrastructure.daemon.models import (
    AgentWorkplaceBindingModel,
    RunClaimModel,
)
from armarius.infrastructure.daemon.placement import (
    CARRIED_BY_DAEMON,
    SqlPlacementRepository,
)
from armarius.infrastructure.database.engine import get_sessionmaker
from armarius.infrastructure.database.models import (
    ProjectLeaderConversationModel,
    RunModel,
)
from armarius.main import app
from armarius.shared.clock import utcnow
from armarius.shared.config import settings
from tests.support.agents import invite_agent
from tests.support.machines import LinkedMachine, auth, link_machine

pytestmark = pytest.mark.anyio


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


class Chatting:
    """A Leader that works on a machine, the project it leads, and that machine's token."""

    def __init__(self, machine: LinkedMachine, marius_id: str, project_id: str) -> None:
        self.machine = machine
        self.marius_id = marius_id
        self.project_id = project_id

    @property
    def headers(self) -> dict[str, str]:
        return self.machine.headers

    @property
    def as_machine(self) -> dict[str, str]:
        return auth(self.machine.token)


async def _an_agent(c: AsyncClient, email: str, *, hostname: str = "thinkpad") -> tuple:
    """A linked machine and one agent created on it, through the routes a person uses.

    Nothing here says which runtime. That is the subject: the agent comes out of the create
    route already carried by whatever its workplace declares.
    """
    machine = await link_machine(c, email, hostname=hostname)
    agent = await invite_agent(
        c,
        machine.workspace_id,
        machine.headers,
        name=f"Marin-{uuid4().hex[:4]}",
        workplace_id=machine.workplace_id,
        adapter_type=None,
    )
    return machine, agent


async def _a_leader_on_a_machine(
    c: AsyncClient, email: str, *, hostname: str = "thinkpad"
) -> Chatting:
    """An agent seated as the Leader of a real project, on a real machine, and online.

    Online is not decoration here: an offline Leader disables the chat outright, which is a
    rule of its own and is proven where it belongs. Contact is recorded through the engine
    every `/agent/*` route records it through, rather than by holding a run open: a run held
    for liveness alone would still be holding a slot on this machine when the chat's own turn
    goes looking for one, and the shelf would look empty for a reason that has nothing to do
    with what these tests measure.
    """
    machine, agent = await _an_agent(c, email, hostname=hostname)
    await app.state.container.liveness.record_signal(UUID(agent["id"]))
    made = await c.post(
        f"/v1/workspaces/{machine.workspace_id}/projects",
        headers=machine.headers,
        json={
            "name": f"Apollo-{uuid4().hex[:4]}",
            "description": "Chở việc xuống máy",
            "leader": {"description": "Điều phối công việc.", "marius_id": agent["id"]},
            "roles": [
                {"title": "Người làm", "seats": 1, "description": "Làm việc được giao."}
            ],
        },
    )
    assert made.status_code == 201, made.text
    return Chatting(machine, agent["id"], made.json()["id"])


async def _say(c: AsyncClient, chatting: Chatting, text: str):
    return await c.post(
        f"/v1/projects/{chatting.project_id}/leader-chat/messages",
        headers=chatting.headers,
        json={"message": text},
    )


async def _conversation(project_id: str) -> ProjectLeaderConversationModel:
    async with get_sessionmaker()() as session:
        row = await session.execute(
            select(ProjectLeaderConversationModel).where(
                ProjectLeaderConversationModel.project_id == UUID(str(project_id))
            )
        )
        return row.scalar_one()


async def _settled(project_id: str, *, attempts: int = 200):
    """The conversation once its turn is over — or as it stands after the last look."""
    for _ in range(attempts):
        conversation = await _conversation(project_id)
        if conversation.state != str(ChatState.THINKING):
            return conversation
        await asyncio.sleep(0.02)
    return await _conversation(project_id)


async def _driving_run(project_id: str, *, attempts: int = 200) -> UUID:
    """The run this chat handed its turn to, once the hand-over has happened."""
    for _ in range(attempts):
        conversation = await _conversation(project_id)
        if conversation.driving_run_id is not None:
            return conversation.driving_run_id
        await asyncio.sleep(0.02)
    raise AssertionError("lượt nói không được giao cho lượt chạy nào")


async def _run(run_id: UUID) -> RunModel:
    async with get_sessionmaker()() as session:
        return await session.get(RunModel, run_id)


async def _shelf(run_id: UUID) -> RunClaimModel | None:
    async with get_sessionmaker()() as session:
        return await session.get(RunClaimModel, run_id)


def _heard(project_id: str) -> list[tuple[str, dict]]:
    """Everything said on this chat's own channel, oldest first."""
    bus = app.state.container.control_bus
    return [(e.type, e.data) for e in bus.backlog(f"leader-chat:{project_id}")]


async def _machine_takes(chatting: Chatting, c: AsyncClient, run_id: UUID) -> int:
    """The machine claims the work and says the agent is up — its own two doors."""
    claimed = await c.post(
        "/daemon/runs/claim",
        headers=chatting.as_machine,
        json={"workplace_ids": [chatting.machine.workplace_id], "free_slots": 1},
    )
    assert claimed.status_code == 200, claimed.text
    mine = [r for r in claimed.json()["runs"] if r["run_id"] == str(run_id)]
    assert mine, f"cửa nhận việc không đưa ra lượt chạy {run_id}: {claimed.text}"
    started = await c.post(
        f"/daemon/runs/{run_id}/start",
        headers=chatting.as_machine,
        json={"session_handle": ""},
    )
    assert started.status_code == 200, started.text
    return mine[0]["first_seq"]


async def _machine_says(
    chatting: Chatting, c: AsyncClient, run_id: UUID, seq: int, text: str
) -> None:
    said = await c.post(
        f"/daemon/runs/{run_id}/events",
        headers=chatting.as_machine,
        json={"events": [{"seq": seq, "type": "assistant.message", "payload": {"text": text}}]},
    )
    assert said.status_code in (200, 202), said.text


async def _machine_finishes(
    chatting: Chatting, c: AsyncClient, run_id: UUID, *, status: str = "completed"
) -> None:
    done = await c.post(
        f"/daemon/runs/{run_id}/finish",
        headers=chatting.as_machine,
        json={"status": status},
    )
    assert done.status_code == 200, done.text


# ── the place decides ─────────────────────────────────────────────────────────────


async def test_an_agent_is_carried_by_whoever_the_place_it_was_put_at_says() -> None:
    """Tạo agent không nhận runtime nào cả — nó chép lại lời khai của chỗ làm.

    Trước đợt này, `AgentService.create` mang sẵn `"echo"` làm mặc định, nên **mọi** agent
    từng được tạo qua giao diện đều đi một con đường dựng cho bản thử. Chỗ sửa không phải là
    đổi hằng số ấy sang `"daemon"`: đó vẫn là tầng nghiệp vụ gọi tên một runtime, thứ Hiến
    pháp III cấm. Chỗ làm khai, tầng nghiệp vụ chép.
    """
    async with _client() as c:
        _, agent = await _an_agent(c, "carried@example.com")

        assert agent["adapter_type"] == CARRIED_BY_DAEMON, agent["adapter_type"]


async def test_the_host_agent_is_made_the_same_way_as_any_other() -> None:
    """Tác nhân Không gian cũng đi lối ấy — nó là agent, không phải một loại riêng.

    Đáng đo riêng vì nó là agent duy nhất được tạo kèm một cờ, và buổi phỏng vấn dựng đội
    (T048a) gọi thẳng `dispatch` trên runtime của chính nó. Nếu cờ ấy kéo theo một lối tạo
    khác thì buổi phỏng vấn sẽ chạy trên một đường và mọi thứ còn lại trên một đường khác.
    """
    async with _client() as c:
        machine = await link_machine(c, "host@example.com")
        host = await invite_agent(
            c,
            machine.workspace_id,
            machine.headers,
            name="Tác nhân",
            workplace_id=machine.workplace_id,
            is_workspace_agent=True,
            adapter_type=None,
        )

        assert host["adapter_type"] == CARRIED_BY_DAEMON, host["adapter_type"]


async def test_a_place_that_names_nobody_takes_no_agent(monkeypatch) -> None:
    """Chỗ làm không khai được ai chở việc thì không nhận agent nào.

    Không lỗi nào của người dùng dẫn tới đây. Từ chối vẫn là đúng: một agent tạo ra mà không
    có câu trả lời cho *ai làm việc của nó* là một agent không cú gọi dậy nào với tới được, và
    nó sẽ hỏng ở lượt nói đầu tiên thay vì hỏng ở đây.
    """
    real = SqlPlacementRepository.get

    async def silent(self, workspace_id, placement_id):
        found = await real(self, workspace_id, placement_id)
        return None if found is None else Placement(
            id=found.id,
            workspace_id=found.workspace_id,
            ready=found.ready,
            not_ready_reason=found.not_ready_reason,
            options=found.options,
        )

    monkeypatch.setattr(SqlPlacementRepository, "get", silent)
    async with _client() as c:
        machine = await link_machine(c, "silentplace@example.com")
        refused = await c.post(
            f"/v1/workspaces/{machine.workspace_id}/mariuses",
            headers=machine.headers,
            json={"name": "Marin", "workplace_id": machine.workplace_id},
        )

        assert refused.status_code == 400, refused.text
        assert PLACEMENT_CARRIES_NOTHING in refused.text


# ── the chat goes down to the machine ─────────────────────────────────────────────


async def test_a_turn_of_the_chat_waits_on_the_shelf_of_the_leaders_machine() -> None:
    """Người chủ nhắn một câu thì lượt nói ấy nằm chờ trên kệ của máy Trưởng dự án.

    Cái chat không phải bản nhỏ của lối gọi dậy: nó không có đầu việc nào, nên lượt chạy nó
    mở ra là **cấp dự án**. Và nó phải nằm ở *đang chờ*: cửa nhận việc lấy việc theo trạng
    thái ấy, nên đánh dấu đang chạy lúc mới giao đi là giao cho một cái kệ không ai với tới.
    """
    async with _client() as c:
        chatting = await _a_leader_on_a_machine(c, "shelf-chat@example.com")

        sent = await _say(c, chatting, "Kế hoạch tuần này thế nào?")
        assert sent.status_code == 200, sent.text
        run_id = await _driving_run(chatting.project_id)

        run = await _run(run_id)
        assert run.status == RunStatus.QUEUED.value, run.status
        assert run.project_id is not None and run.task_id is None
        assert str(run.marius_id) == chatting.marius_id
        row = await _shelf(run_id)
        assert row is not None, "lượt nói không được đặt lên kệ nào cả"
        assert str(row.workplace_id) == chatting.machine.workplace_id


async def test_the_chat_stays_shut_while_the_work_is_still_out() -> None:
    """Lượt thứ hai vẫn bị từ chối trong lúc lượt đầu còn ở ngoài kia.

    Luật lượt-lần-lượt cũ đo bằng `state`, và trên đường cũ `state` trở lại *rảnh* ngay trong
    cùng lời gọi. Trên đường này lượt nói còn chưa bắt đầu lúc lời gọi trả về, nên nếu cú
    buông tay làm rớt mất `state` thì người chủ gõ được câu thứ hai — và Trưởng dự án nhận hai
    lượt nói cho một câu chuyện.
    """
    async with _client() as c:
        chatting = await _a_leader_on_a_machine(c, "busy-chat@example.com")

        assert (await _say(c, chatting, "Câu một")).status_code == 200
        await _driving_run(chatting.project_id)
        again = await _say(c, chatting, "Câu hai")

        assert again.status_code == 409, again.text
        assert (await _conversation(chatting.project_id)).state == str(ChatState.THINKING)


async def test_the_reply_is_what_the_machine_wrote_down() -> None:
    """Câu trả lời dựng lại từ bản ghi của lượt chạy, không từ thứ tiến trình này cầm.

    Đây là điều làm cái kết sống sót qua một lần khởi động lại: tiến trình này không ngồi xem
    lượt nói, nên thứ duy nhất nói được Trưởng dự án đã nói gì là những dòng máy ghi xuống.
    """
    async with _client() as c:
        chatting = await _a_leader_on_a_machine(c, "reply@example.com")
        await _say(c, chatting, "Tuần này ưu tiên gì?")
        run_id = await _driving_run(chatting.project_id)

        seq = await _machine_takes(chatting, c, run_id)
        await _machine_says(chatting, c, run_id, seq, "Ưu tiên cổng đăng nhập. ")
        await _machine_says(chatting, c, run_id, seq + 1, "Rồi mới tới báo cáo.")
        await _machine_finishes(chatting, c, run_id)

        conversation = await _settled(chatting.project_id)
        assert conversation.state == str(ChatState.IDLE), conversation.state
        said = [t for t in conversation.transcript if t["role"] == "leader"]
        assert said and said[-1]["text"] == "Ưu tiên cổng đăng nhập. Rồi mới tới báo cáo."


async def test_a_reply_too_long_to_keep_inline_comes_back_whole() -> None:
    """Câu dài bị cắt ngắn lúc ghi thì phải được đi lấy phần còn lại (FR-049).

    Dựng lại câu trả lời từ mấy dòng mở đầu là đặt vào miệng Trưởng dự án một câu **bị cắt mà
    không ai nói là bị cắt** — tệ hơn hẳn một câu thiếu hẳn, vì trên màn hình nó trông như một
    câu trả lời trọn vẹn.
    """
    async with _client() as c:
        chatting = await _a_leader_on_a_machine(c, "long-reply@example.com")
        await _say(c, chatting, "Kể tôi nghe hết đi.")
        run_id = await _driving_run(chatting.project_id)

        seq = await _machine_takes(chatting, c, run_id)
        whole = "A" * (settings.run_event_inline_bytes * 2)
        await _machine_says(chatting, c, run_id, seq, whole)
        await _machine_finishes(chatting, c, run_id)

        conversation = await _settled(chatting.project_id)
        said = [t for t in conversation.transcript if t["role"] == "leader"]
        assert said and said[-1]["text"] == whole


async def test_the_patron_sees_the_reply_arriving_rather_than_a_still_box() -> None:
    """Từng đoạn máy báo về hiện lên ngay, chứ không đợi cả câu rơi xuống một lần.

    Trên đường cũ, cái chat tự nghe từng mẩu chảy qua tay mình. Đường này không đi qua tay
    nó — nếu không có ai chuyển tiếp thì người chủ ngồi nhìn một cái khung trống suốt cả lượt
    nói, rồi thấy nguyên câu hiện ra ở cuối (FR-046).
    """
    async with _client() as c:
        chatting = await _a_leader_on_a_machine(c, "streaming@example.com")
        await _say(c, chatting, "Nói dần cho tôi nghe.")
        run_id = await _driving_run(chatting.project_id)

        seq = await _machine_takes(chatting, c, run_id)
        await _machine_says(chatting, c, run_id, seq, "Đang đọc bảng công việc")

        heard = _heard(chatting.project_id)
        arriving = [d["text"] for kind, d in heard if kind == "assistant.delta"]
        assert arriving == ["Đang đọc bảng công việc"], heard


async def test_a_leader_with_nowhere_left_to_work_ends_its_turn_here() -> None:
    """Không ai nhận lượt nói thì lượt nói khép lại ngay tại chỗ nó được chào mời.

    Bỏ mặc nó là hỏng kiểu tệ nhất mà cái chat có: khung chat kẹt ở *đang nghĩ* sau một lượt
    chạy **không ai đến lấy**, nên mọi câu tiếp theo của người chủ ăn `409` — người chủ bị
    khoá khỏi chính khung chat của mình, mà không chỗ nào trên màn hình giải thích nổi.
    """
    async with _client() as c:
        chatting = await _a_leader_on_a_machine(c, "nowhere@example.com")
        async with get_sessionmaker()() as session:
            await session.execute(
                delete(AgentWorkplaceBindingModel).where(
                    AgentWorkplaceBindingModel.marius_id == UUID(chatting.marius_id)
                )
            )
            await session.commit()

        assert (await _say(c, chatting, "Còn ai ở đó không?")).status_code == 200
        conversation = await _settled(chatting.project_id)

        assert conversation.state == str(ChatState.FAILED), conversation.state
        run = await _run(conversation.driving_run_id)
        assert run.status == RunStatus.FAILED.value, run.status
        assert run.error == "agent_has_no_workplace", run.error
        assert (await _say(c, chatting, "Thử lại nào")).status_code == 200


async def test_a_turn_that_hung_out_there_gives_the_chat_back() -> None:
    """Lượt nói treo ngoài kia thì người quét dọn phải trả khung chat lại cho người chủ.

    Trên đường cũ, một lượt nói không bao giờ treo quá hạn của chính cú gọi. Trên đường này
    tiến trình đây không cầm gì cả, nên **người quét dọn là cái hạn duy nhất** — mà nó tự ghi
    cái kết của mình, không đi qua cửa khép lượt chạy. Thiếu mối nối ấy thì khung chat kẹt ở
    *đang nghĩ* vĩnh viễn: người chủ bị khoá khỏi chính khung chat của mình, và không màn hình
    nào giải thích được vì sao.
    """
    async with _client() as c:
        chatting = await _a_leader_on_a_machine(c, "hung@example.com")
        await _say(c, chatting, "Có ai không?")
        run_id = await _driving_run(chatting.project_id)
        await _machine_takes(chatting, c, run_id)
        long_ago = utcnow() - timedelta(days=1)
        async with get_sessionmaker()() as session:
            await session.execute(
                update(RunModel)
                .where(RunModel.id == run_id)
                .values(last_output_at=long_ago, started_at=long_ago)
            )
            await session.commit()

        reaped = await app.state.container.liveness_watchdog.reap_hung_runs()

        assert reaped >= 1, "người quét dọn không nhặt lượt chạy treo nào"
        conversation = await _settled(chatting.project_id)
        assert conversation.state == str(ChatState.FAILED), conversation.state
        assert (await _say(c, chatting, "Thử lại")).status_code == 200


async def test_a_run_driving_no_chat_leaves_every_chat_alone() -> None:
    """Cửa khép lượt chạy gọi cho **mọi** lượt chạy, nên nó phải im lặng với phần lớn.

    Một lượt chạy của một đầu việc bình thường mà khép nhầm một khung chat sẽ ghi vào cuộc
    trò chuyện một câu trả lời rỗng và mở khoá một lượt còn đang chạy dở.
    """
    async with _client() as c:
        chatting = await _a_leader_on_a_machine(c, "unrelated@example.com")
        await _say(c, chatting, "Đang nói dở")
        driving = await _driving_run(chatting.project_id)

        await app.state.container.wake_engine.conclude_run(
            uuid4(), status=RunStatus.COMPLETED
        )

        conversation = await _conversation(chatting.project_id)
        assert conversation.state == str(ChatState.THINKING), conversation.state
        assert conversation.driving_run_id == driving
