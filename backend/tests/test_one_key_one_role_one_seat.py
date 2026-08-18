"""Khoá vai là **duy nhất trong một dự án**, và một vai không giữ nhiều hơn số chỗ nó khai (T202).

Hai nửa của cùng một chuyện, và ràng buộc duy nhất của T199 chỉ đóng được nửa dưới.

**Nửa trên** — mọi thứ gọi tên một vai đều gọi bằng khoá: cửa roster, bản kế hoạch Trưởng dự
án soạn lúc onboarding, `_role_by_key`, `leader_role_ids`. `add_role` đã từ chối khoá trùng,
nhưng mỗi lần một vai. Cả một roster vào cùng lúc thì chưa từng đi qua phép soát ấy, mà cửa
onboarding lại đưa thẳng khoá agent tự soạn vào — nên hai vai cùng tên "Backend" thành hai
dòng chung khoá, và mọi lượt tra theo khoá trả về dòng nào là tuỳ thứ tự.

**Nửa dưới** — `(project_id, role_id, marius_id)` chặn *một người ngồi hai dòng*, nhưng
không chặn *hai người ngồi một vai một chỗ*. Đấy đúng là nửa quyết định `leader_marius_id`
trả về ai khi ghế Trưởng bị trao hai lần cho hai agent khác nhau.
"""

from __future__ import annotations

import pytest

from armarius.application.use_cases.mariuses import MariusService
from armarius.application.use_cases.projects import ProjectService, RoleSpec
from armarius.application.use_cases.seats import leader_marius_id
from armarius.application.use_cases.workspaces import WorkspaceService
from armarius.domain.services import project_rules
from armarius.shared.errors import BadRequest

pytestmark = pytest.mark.asyncio


def _roster(**extra: object) -> list[RoleSpec]:
    roles = [
        RoleSpec(key="leader", title="Trưởng dự án", seats=1, is_leader=True,
                 description="Điều phối dự án."),
        RoleSpec(key="backend", title="Backend", seats=int(extra.get("seats", 1)),
                 description="Lo phần máy chủ."),
    ]
    return roles


async def _agent(uow_factory, ws_id, name: str):  # noqa: ANN001, ANN202
    return await MariusService(uow_factory).register(
        workspace_id=ws_id, name=name, role="Backend", skills=[],
        adapter_type="echo", adapter_config={},
    )


# ── nửa trên: một khoá, một vai ───────────────────────────────────────────────


async def test_a_roster_with_two_roles_on_one_key_is_refused() -> None:
    """Phép soát nằm ở `validate_plan`, nên cả cửa HTTP lẫn cửa onboarding đều đi qua nó."""
    roles = [
        project_rules.Role(key="leader", title="Trưởng", seats=1, is_leader=True,
                           description="Điều phối."),
        project_rules.Role(key="backend", title="Backend", seats=1, description="Máy chủ."),
        project_rules.Role(key="backend", title="Backend 2", seats=1, description="Máy chủ."),
    ]
    with pytest.raises(project_rules.InvalidProjectPlan) as caught:
        project_rules.validate_plan(roles)
    assert caught.value.code == "role_keys_must_be_unique"
    assert "backend" in caught.value.params["keys"]


async def test_creating_a_project_with_a_repeated_key_is_refused(uow_factory) -> None:  # noqa: ANN001
    ws = await WorkspaceService(uow_factory).create_workspace("WS")
    roles = _roster() + [
        RoleSpec(key="backend", title="Backend nữa", seats=1, description="Cũng máy chủ.")
    ]
    with pytest.raises(project_rules.InvalidProjectPlan):
        await ProjectService(uow_factory).create_project(ws.id, "Apollo", roles=roles)


async def test_a_roster_of_distinct_keys_still_goes_in(uow_factory) -> None:  # noqa: ANN001
    """Phép soát mới không được chặn nhầm roster hợp lệ."""
    ws = await WorkspaceService(uow_factory).create_workspace("WS")
    project = await ProjectService(uow_factory).create_project(
        ws.id, "Apollo", roles=_roster()
    )
    assert project is not None


async def test_the_onboarding_door_renumbers_instead_of_dying(uow_factory) -> None:  # noqa: ANN001
    """Khoá do agent soạn thì máy tự đánh số lại, không bắt người chủ nói lại từ đầu.

    `validate_plan` từ chối thẳng khoá trùng — đúng với roster người gõ tay. Nhưng ở cửa
    onboarding tác giả là một mô hình vừa với tay lấy đúng một chữ hai lần, và giết cả lượt
    trò chuyện vì chuyện chọn chữ của máy là bắt người chủ trả giá cho lỗi của máy.
    """
    from armarius.application.use_cases.onboarding_session import plan_from_collected

    plan = plan_from_collected(
        {
            "draft": {
                "objective": "Dựng trang bán hàng.",
                "roster": [
                    {"key": "backend", "title": "Backend", "seats": 1, "description": "Máy chủ."},
                    {"key": "backend", "title": "Backend 2", "seats": 1, "description": "Máy chủ."},
                ],
            }
        }
    )
    keys = [r.key for r in plan["roles"]]
    assert len(keys) == len(set(keys)), keys
    assert "backend" in keys and "backend2" in keys
    # Và bản kế hoạch ấy đi lọt phép soát, tức onboarding không còn chết ở đây.
    project_rules.validate_plan(
        [
            project_rules.Role(
                key=r.key, title=r.title, seats=r.seats,
                is_leader=r.is_leader, description=r.description,
            )
            for r in plan["roles"]
        ]
    )


# ── nửa dưới: một chỗ, một người ──────────────────────────────────────────────


async def test_a_one_seat_role_does_not_hold_two_agents(uow_factory) -> None:  # noqa: ANN001
    ws = await WorkspaceService(uow_factory).create_workspace("WS")
    projects = ProjectService(uow_factory)
    project = await projects.create_project(ws.id, "Apollo", roles=_roster())
    first, second = (await _agent(uow_factory, ws.id, "A"), await _agent(uow_factory, ws.id, "B"))

    await projects.grant_seat(project.id, "leader", first.id, system=True)
    with pytest.raises(BadRequest) as caught:
        await projects.grant_seat(project.id, "leader", second.id, system=True)

    assert caught.value.code == "role_seats_full"
    # Người ngồi trước vẫn ngồi, và câu trả lời "ai là Trưởng" không còn tuỳ thứ tự dòng.
    async with uow_factory() as uow:
        assert await leader_marius_id(uow, project.id) == first.id


async def test_a_two_seat_role_holds_two_agents(uow_factory) -> None:  # noqa: ANN001
    """Chặn theo `seats`, không phải chặn cứng ở một người."""
    ws = await WorkspaceService(uow_factory).create_workspace("WS")
    projects = ProjectService(uow_factory)
    project = await projects.create_project(ws.id, "Apollo", roles=_roster(seats=2))
    first, second = (await _agent(uow_factory, ws.id, "A"), await _agent(uow_factory, ws.id, "B"))

    await projects.grant_seat(project.id, "backend", first.id, system=True)
    await projects.grant_seat(project.id, "backend", second.id, system=True)

    seated = [g for g in await projects.list_seat_grants(project.id) if g.role_key == "backend"]
    assert len(seated) == 2


async def test_a_seat_given_back_frees_the_chair_again(uow_factory) -> None:  # noqa: ANN001
    """Đếm theo dòng đang sống, nên trả ghế là chỗ ấy trống thật."""
    ws = await WorkspaceService(uow_factory).create_workspace("WS")
    projects = ProjectService(uow_factory)
    project = await projects.create_project(ws.id, "Apollo", roles=_roster())
    first, second = (await _agent(uow_factory, ws.id, "A"), await _agent(uow_factory, ws.id, "B"))

    await projects.grant_seat(project.id, "leader", first.id, system=True)
    await projects.revoke_seat_by_role(project.id, first.id, "leader", system=True)
    await projects.grant_seat(project.id, "leader", second.id, system=True)

    async with uow_factory() as uow:
        assert await leader_marius_id(uow, project.id) == second.id
