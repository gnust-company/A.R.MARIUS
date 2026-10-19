"""WorkspaceAgentService — host seat via workspace.workspace_agent_id (#32).

`ensure_workspace_agent` is lookup-only and stays that way: it answers *who holds the seat*
and conjures nobody. What changed (FR-110) is that there is now a door that does create one —
`provide_host` — called once when a workspace is made, and `place_host`, which puts that host
to work on the runtime its owner chose (spec 003 FR-112, FR-125, FR-128 — revised 2026-10-12:
nothing places the host by itself any more).

Half of #63 is reversed by that, deliberately. #63 forbade auto-creation because an agent
without a gateway address and a key was a shell that could neither wake nor authenticate its
callbacks. Since spec 002 no agent has either of those things: what carries a turn is a
runtime, and a runtime arrives when somebody links a machine — after the workspace exists. So
what #63 refused (a shell that can never work) is not what `provide_host` makes (an agent not
placed *yet*), and the second is a state FR-007f defined before anything could reach it.

The onboarding playbook is still injected into the agent's prompt when a project-setup chat
starts (#61), so designation remains purely about who holds the seat.
"""

from __future__ import annotations

from uuid import uuid4

import pytest

from armarius.application.use_cases.enrollment import PlacementNotReady
from armarius.application.use_cases.workspace_agent import (
    HOST_DEFAULT_INSTRUCTIONS,
    HOST_NAME,
    WORKSPACE_AGENT_ROLE,
    WorkspaceAgentService,
)
from armarius.domain.entities.marius import Marius
from armarius.domain.entities.workspace import Workspace
from armarius.shared.errors import Conflict, NotFound
from tests.support.fakes import FakeUowFactory, a_placement


def _factory_with_workspace() -> tuple[FakeUowFactory, Workspace]:
    factory = FakeUowFactory()
    ws = Workspace(name="Studio", slug="studio", owner_user_id="u1")
    factory.store.workspaces[ws.id] = ws
    return factory, ws


def _add_marius(factory: FakeUowFactory, ws: Workspace, name: str, role: str = "") -> Marius:
    m = Marius(workspace_id=ws.id, name=name, role=role, adapter_type="echo")
    factory.store.mariuses[m.id] = m
    return m


async def test_ensure_returns_none_when_no_host_designated() -> None:
    """No operator invited+seated a host → ensure does not conjure one (#63)."""
    factory, ws = _factory_with_workspace()
    svc = WorkspaceAgentService(factory)

    assert await svc.ensure_workspace_agent(ws.id) is None
    assert factory.store.workspaces[ws.id].workspace_agent_id is None
    assert not factory.store.mariuses  # nothing was created


async def test_ensure_returns_the_designated_host() -> None:
    factory, ws = _factory_with_workspace()
    svc = WorkspaceAgentService(factory)
    host = _add_marius(factory, ws, "Host")
    await svc.designate(ws.id, host.id)

    found = await svc.ensure_workspace_agent(ws.id)
    assert found is not None
    assert found.id == host.id


async def test_ensure_backfills_the_pointer_for_a_legacy_host() -> None:
    factory, ws = _factory_with_workspace()
    legacy = _add_marius(factory, ws, "Old Host", role=WORKSPACE_AGENT_ROLE)
    svc = WorkspaceAgentService(factory)

    agent = await svc.ensure_workspace_agent(ws.id)

    assert agent is not None
    assert agent.id == legacy.id
    assert factory.store.workspaces[ws.id].workspace_agent_id == legacy.id


async def test_designation_is_idempotent() -> None:
    factory, ws = _factory_with_workspace()
    svc = WorkspaceAgentService(factory)
    host = _add_marius(factory, ws, "Host")
    await svc.designate(ws.id, host.id)

    first = await svc.ensure_workspace_agent(ws.id)
    second = await svc.ensure_workspace_agent(ws.id)
    assert first is not None and second is not None
    assert first.id == second.id == host.id


async def test_designate_swaps_and_keeps_the_old_host_as_plain_agent() -> None:
    factory, ws = _factory_with_workspace()
    svc = WorkspaceAgentService(factory)
    old = _add_marius(factory, ws, "Old")
    await svc.designate(ws.id, old.id)  # seat the first host
    new = _add_marius(factory, ws, "Fresh")

    promoted = await svc.designate(ws.id, new.id)

    assert promoted.id == new.id
    assert promoted.role == WORKSPACE_AGENT_ROLE
    assert factory.store.workspaces[ws.id].workspace_agent_id == new.id
    # The old host survives as a plain agent — demoted, not revoked (#32).
    demoted = factory.store.mariuses[old.id]
    assert demoted.role == ""
    # Idempotent: designating the sitting host again changes nothing.
    again = await svc.designate(ws.id, new.id)
    assert again.id == new.id
    assert factory.store.workspaces[ws.id].workspace_agent_id == new.id


async def test_designate_rejects_a_marius_from_another_workspace() -> None:
    factory, ws = _factory_with_workspace()
    other = Workspace(name="Elsewhere", slug="elsewhere", owner_user_id="u2")
    factory.store.workspaces[other.id] = other
    stranger = _add_marius(factory, other, "Stranger")
    svc = WorkspaceAgentService(factory)

    with pytest.raises(LookupError):
        await svc.designate(ws.id, stranger.id)


async def test_missing_workspace_is_rejected() -> None:
    factory, _ws = _factory_with_workspace()
    svc = WorkspaceAgentService(factory)

    with pytest.raises(LookupError):
        await svc.ensure_workspace_agent(uuid4())


# ── người chủ nhà có mặt từ lúc không gian làm việc có mặt (FR-110, FR-112) ───


async def test_a_workspace_is_given_a_host_that_is_not_placed_anywhere_yet() -> None:
    """Cửa riêng, có tên riêng (FR-114): tạo được người chủ nhà mà không cần runtime nào."""
    factory, ws = _factory_with_workspace()
    svc = WorkspaceAgentService(factory)

    host = await svc.provide_host(ws.id)

    assert host.name == HOST_NAME
    assert host.role == WORKSPACE_AGENT_ROLE
    # Công việc làm nó thành người chủ nhà nằm ở **nửa của sản phẩm**, không ở nửa người chủ
    # viết (FR-007m). Ý của dòng này không đổi — người chủ nhà không có chỉ dẫn thì không biết
    # mình là gì — chỉ là từ nay có hai tác giả, và nó phải đọc đúng tác giả.
    assert host.system_instructions, "người chủ nhà không có chỉ dẫn thì không biết mình là gì"
    # Còn nửa của người chủ bắt đầu bằng chỉ dẫn mặc định (FR-124): cách trò chuyện, không phải
    # việc của người chủ nhà — và đó là ô họ sửa được.
    assert host.instructions == HOST_DEFAULT_INSTRUCTIONS
    # Rỗng là toàn bộ hình dạng của *chưa được đặt chỗ*: thứ chở lượt chạy là câu trả lời của
    # runtime, và chưa có runtime nào để hỏi. Đoán một giá trị ở đây là tầng nghiệp vụ tự đặt
    # tên một runtime (Hiến pháp Điều III).
    assert host.adapter_type == ""
    assert factory.store.attachments.get(host.id) is None
    # Và nó giữ ghế chủ nhà, nên `ensure_workspace_agent` tìm ra đúng nó.
    assert factory.store.workspaces[ws.id].workspace_agent_id == host.id
    assert (await svc.ensure_workspace_agent(ws.id)).id == host.id


async def test_giving_a_workspace_a_host_twice_does_not_make_two() -> None:
    factory, ws = _factory_with_workspace()
    svc = WorkspaceAgentService(factory)

    first = await svc.provide_host(ws.id)
    again = await svc.provide_host(ws.id)

    assert again.id == first.id
    assert len(factory.store.mariuses) == 1


async def test_a_workspace_whose_owner_already_seated_a_host_keeps_theirs() -> None:
    """FR-113: không sinh thêm con nào, và không hạ ghế ai."""
    factory, ws = _factory_with_workspace()
    theirs = _add_marius(factory, ws, "Aurelia", role=WORKSPACE_AGENT_ROLE)
    ws.workspace_agent_id = theirs.id
    svc = WorkspaceAgentService(factory)

    host = await svc.provide_host(ws.id)

    assert host.id == theirs.id
    assert host.name == "Aurelia"
    assert len(factory.store.mariuses) == 1


async def test_a_taken_name_is_stepped_around_rather_than_refused() -> None:
    """Tên là duy nhất trong một không gian làm việc (FR-007h).

    Từ chối ở đây là làm hỏng việc tạo cả một không gian làm việc vì một cái tên hiển thị —
    đổi sai bên rất xa (FR-113).
    """
    factory, ws = _factory_with_workspace()
    # Một agent người dùng tự tạo: có tên ấy, và **có chỗ làm** — cửa tạo agent đòi chọn chỗ làm
    # và không có mặc định (FR-007f), nên không có agent nào của người dùng thiếu nó.
    theirs = _add_marius(factory, ws, HOST_NAME)
    factory.store.attachments[theirs.id] = a_placement(factory, ws.id).id
    svc = WorkspaceAgentService(factory)

    host = await svc.provide_host(ws.id)

    assert host.name != HOST_NAME
    assert host.name.startswith(HOST_NAME)
    assert host.role == WORKSPACE_AGENT_ROLE


class _Measured:
    """Ghi lại ai được kiểm sống ngay — đúng câu FR-006e hỏi, không cần dựng cả bộ kiểm."""

    def __init__(self) -> None:
        self.asked: list = []

    async def placement_changed(self, marius_ids, now=None) -> None:
        self.asked.extend(marius_ids)


async def test_the_runtime_its_owner_chose_is_where_the_host_goes_to_work() -> None:
    """FR-125, FR-126: chỗ làm, thứ chở lượt chạy, và chữ của người chủ — cùng một lần."""
    factory, ws = _factory_with_workspace()
    measured = _Measured()
    svc = WorkspaceAgentService(factory, liveness=measured)
    host = await svc.provide_host(ws.id)
    place = a_placement(factory, ws.id, carried_by="claude_code")

    placed = await svc.place_host(ws.id, host.id, place.id, instructions="Ngắn thôi.")

    assert placed.id == host.id
    assert factory.store.attachments[host.id] == place.id
    # Thứ chở lượt chạy của nó là câu trả lời của runtime, chép xuống nguyên văn.
    assert factory.store.mariuses[host.id].adapter_type == "claude_code"
    assert factory.store.mariuses[host.id].instructions == "Ngắn thôi."
    # Kiểm sống ngay, không đợi vòng kiểm định kỳ (FR-006e).
    assert measured.asked == [host.id]


async def test_without_instructions_the_host_keeps_the_ones_it_has() -> None:
    factory, ws = _factory_with_workspace()
    svc = WorkspaceAgentService(factory)
    host = await svc.provide_host(ws.id)
    place = a_placement(factory, ws.id)

    await svc.place_host(ws.id, host.id, place.id)

    assert factory.store.mariuses[host.id].instructions == HOST_DEFAULT_INSTRUCTIONS


async def test_a_host_already_working_is_not_moved() -> None:
    """Đặt rồi thì không đổi (FR-007). Người chủ nhà không phải ngoại lệ của luật ấy."""
    factory, ws = _factory_with_workspace()
    svc = WorkspaceAgentService(factory)
    host = await svc.provide_host(ws.id)
    first = a_placement(factory, ws.id, carried_by="claude_code")
    await svc.place_host(ws.id, host.id, first.id)

    second = a_placement(factory, ws.id, carried_by="codex")
    with pytest.raises(Conflict) as refused:
        await svc.place_host(ws.id, host.id, second.id, instructions="khác")
    assert refused.value.code == "agent_already_placed"
    assert factory.store.attachments[host.id] == first.id
    assert factory.store.mariuses[host.id].adapter_type == "claude_code"
    assert factory.store.mariuses[host.id].instructions == HOST_DEFAULT_INSTRUCTIONS


async def test_a_runtime_that_cannot_take_work_is_refused_and_nothing_changes() -> None:
    factory, ws = _factory_with_workspace()
    svc = WorkspaceAgentService(factory)
    host = await svc.provide_host(ws.id)
    shut = a_placement(factory, ws.id, ready=False, not_ready_reason="cli_removed")
    silent = a_placement(factory, ws.id, carried_by="")

    for place, reason in ((shut, "cli_removed"), (silent, "placement_carries_nothing")):
        with pytest.raises(PlacementNotReady) as refused:
            await svc.place_host(ws.id, host.id, place.id, instructions="x")
        assert refused.value.code == "placement_not_ready"
        assert refused.value.params == {"reason": reason}
    assert factory.store.attachments.get(host.id) is None
    assert factory.store.mariuses[host.id].adapter_type == ""
    assert factory.store.mariuses[host.id].instructions == HOST_DEFAULT_INSTRUCTIONS


async def test_a_runtime_of_another_workspace_is_not_found() -> None:
    factory, ws = _factory_with_workspace()
    other = Workspace(name="Khác", slug="khac", owner_user_id="u1")
    factory.store.workspaces[other.id] = other
    svc = WorkspaceAgentService(factory)
    host = await svc.provide_host(ws.id)
    elsewhere = a_placement(factory, other.id)

    with pytest.raises(NotFound) as refused:
        await svc.place_host(ws.id, host.id, elsewhere.id)
    assert refused.value.code == "placement_not_found"


async def test_only_the_host_can_be_given_a_place_after_it_was_made() -> None:
    """Gỡ máy thì agent thường mất chỗ làm. Cửa này không được thành đường đặt lại cho nó."""
    factory, ws = _factory_with_workspace()
    svc = WorkspaceAgentService(factory)
    await svc.provide_host(ws.id)
    plain = _add_marius(factory, ws, "Decima")
    place = a_placement(factory, ws.id)

    with pytest.raises(Conflict) as refused:
        await svc.place_host(ws.id, plain.id, place.id)
    assert refused.value.code == "placement_is_fixed"
    assert factory.store.attachments.get(plain.id) is None


async def test_losing_a_race_is_the_answer_to_arriving_late(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Hai cửa sổ cùng bấm xong (FR-127): lần ghi tới sau nhận đúng `agent_already_placed`.

    Cuộc đua này cái kho trong bộ nhớ **không dựng được một mình**: `placed_at` và `attach` đọc
    cùng một cái dict, nên nó không bao giờ nói *chưa đặt* rồi lại từ chối. Nên chỗ từ chối được
    thay vào — đúng cái xảy ra khi giao dịch của cửa sổ kia chưa commit lúc cửa sổ này đi hỏi,
    và đã commit lúc cửa sổ này đi ghi. Bài đua thật trên Postgres ở
    `test_host_placement_races.py`.
    """
    factory, ws = _factory_with_workspace()
    svc = WorkspaceAgentService(factory)
    host = await svc.provide_host(ws.id)
    place = a_placement(factory, ws.id, carried_by="claude_code")

    async def already(*_args: object, **_kwargs: object) -> None:
        raise Conflict("agent_already_placed")

    async with factory() as uow:
        monkeypatch.setattr(type(uow.placements), "attach", already)

    with pytest.raises(Conflict) as refused:
        await svc.place_host(ws.id, host.id, place.id, instructions="x")
    assert refused.value.code == "agent_already_placed"
    # Và không để lại nửa vời: không thứ chở lượt chạy, không chữ mới.
    assert factory.store.mariuses[host.id].adapter_type == ""
    assert factory.store.mariuses[host.id].instructions == HOST_DEFAULT_INSTRUCTIONS


async def test_a_host_created_but_never_seated_is_taken_up_rather_than_duplicated() -> None:
    """Làm ra người chủ nhà mất **hai** lần commit: con agent, rồi cái ghế.

    Hai lần vì dự án cố ý tách *tạo agent* khỏi *cho agent một cái ghế* (Hiến pháp V), và vì chỉ
    một module được dựng agent. Chết ở giữa hai lần ấy để lại một con không ai trỏ tới — và nếu
    không nhận nó lại thì lần gọi sau đẻ ra một con thứ hai tên `Livia 2`.
    """
    factory, ws = _factory_with_workspace()
    svc = WorkspaceAgentService(factory)
    # Đúng thứ `create_unplaced` để lại khi cái ghế chưa được ghi: tên ấy, không vai, và không
    # có hàng buộc nào vào một chỗ làm.
    orphan = Marius(workspace_id=ws.id, name=HOST_NAME, role="")
    factory.store.mariuses[orphan.id] = orphan
    assert factory.store.attachments.get(orphan.id) is None

    host = await svc.provide_host(ws.id)

    assert host.id == orphan.id
    assert host.role == WORKSPACE_AGENT_ROLE
    assert len(factory.store.mariuses) == 1, "đẻ thêm một con nữa thay vì nhận lại con dựng dở"
    assert factory.store.workspaces[ws.id].workspace_agent_id == orphan.id


async def test_an_agent_a_person_placed_is_never_mistaken_for_a_half_made_host() -> None:
    """Ba điều kiện của phép nhận lại không được trùng với một agent người dùng tự tạo.

    Người dùng không tạo được agent mà bỏ trống chỗ làm — cửa ấy đòi có và không có mặc định
    (FR-007f) — nên *không có chỗ làm* là trạng thái chỉ `create_unplaced` để lại được.
    """
    factory, ws = _factory_with_workspace()
    svc = WorkspaceAgentService(factory)
    # Một người thật tạo một agent và tình cờ gọi nó là Livia. Nó có chỗ làm.
    theirs = _add_marius(factory, ws, HOST_NAME)
    place = a_placement(factory, ws.id)
    factory.store.attachments[theirs.id] = place.id

    host = await svc.provide_host(ws.id)

    assert host.id != theirs.id, "nhận lầm agent của người dùng làm con dựng dở"
    assert host.name != HOST_NAME
    assert factory.store.mariuses[theirs.id].role == "", "và không được cướp ghế của nó"
