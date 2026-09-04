"""Khoá vai là **duy nhất trong một dự án**, và một vai không giữ nhiều hơn số chỗ nó khai (T202).

Hai nửa của cùng một chuyện, và ràng buộc duy nhất của T199 chỉ đóng được nửa dưới.

**Nửa trên** — mọi thứ gọi tên một vai đều gọi bằng khoá, nên hai dòng chung khoá làm mọi lượt
tra trả về dòng nào là tuỳ thứ tự. Luật ấy còn nguyên và vẫn được đo ở đây; điều đã đổi là
*không ai đưa khoá vào nữa*: từ T039j hệ thống tự dựng đúng hai dòng cho mỗi dự án, nên đường
mà một khoá trùng từng lọt qua — người chủ gõ tay, hay agent soạn lúc onboarding — đã đóng.

**Nửa dưới** — `(project_id, role_id, marius_id)` chặn *một người ngồi hai dòng*, nhưng
không chặn *hai người ngồi một vai một chỗ*. Đấy đúng là nửa quyết định `leader_marius_id`
trả về ai khi ghế Trưởng bị trao hai lần cho hai agent khác nhau.
"""

from __future__ import annotations

import pytest

from armarius.application.use_cases.projects import (
    LEADER_ROLE_KEY,
    MEMBERS_ROLE_KEY,
    ProjectService,
)
from armarius.application.use_cases.seats import leader_marius_id
from armarius.application.use_cases.workspaces import WorkspaceService
from armarius.domain.services import project_rules
from armarius.shared.errors import BadRequest
from tests.support.agents import make_agent

pytestmark = pytest.mark.asyncio


async def _agent(uow_factory, ws_id, name: str):  # noqa: ANN001, ANN202
    return await make_agent(uow_factory, 
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


async def test_the_only_two_keys_a_project_gets_cannot_collide(uow_factory) -> None:  # noqa: ANN001
    """Cửa duy nhất còn dựng roster tự đặt cả hai khoá, nên không còn đường cho khoá trùng."""
    ws = await WorkspaceService(uow_factory).create_workspace("WS")
    project = await ProjectService(uow_factory).create_project(
        ws.id, "Apollo", leader_description="Điều phối dự án."
    )
    keys = [r.key for r in await ProjectService(uow_factory).list_roles(project.id)]

    assert sorted(keys) == sorted([LEADER_ROLE_KEY, MEMBERS_ROLE_KEY])
    assert len(keys) == len(set(keys))


async def test_the_onboarding_draft_carries_no_roster_at_all(uow_factory) -> None:  # noqa: ANN001
    """Chỗ khoá trùng từng lọt vào: nay bản nháp của agent không có roster để mà trùng.

    Trước T039j agent soạn danh sách vai, và máy phải tự đánh số lại khoá vì một mô hình
    với tay lấy đúng một chữ hai lần. Nay agent không soạn vai nào — nó phỏng vấn về **dự
    án**, còn ai vào dự án là người chủ tự chọn trong đám agent của chính họ (FR-007l).
    """
    from armarius.application.use_cases.onboarding_session import plan_from_collected

    plan = plan_from_collected(
        {
            "draft": {
                "objective": "Dựng trang bán hàng.",
                # Kể cả khi có gì sót lại trong bản nháp cũ, nó không đi tới đâu nữa.
                "roster": [
                    {"key": "backend", "title": "Backend", "seats": 1, "description": "Máy chủ."},
                    {"key": "backend", "title": "Backend 2", "seats": 1, "description": "Máy chủ."},
                ],
            }
        }
    )

    assert "roles" not in plan and "roster" not in plan


# ── nửa dưới: một chỗ, một người ──────────────────────────────────────────────


async def test_a_one_seat_role_does_not_hold_two_agents(uow_factory) -> None:  # noqa: ANN001
    """Ghế Trưởng dự án là chỗ duy nhất còn hứa với đúng một agent."""
    ws = await WorkspaceService(uow_factory).create_workspace("WS")
    projects = ProjectService(uow_factory)
    project = await projects.create_project(ws.id, "Apollo", leader_description="Điều phối.")
    first, second = (await _agent(uow_factory, ws.id, "A"), await _agent(uow_factory, ws.id, "B"))

    await projects.seat_leader(project.id, first.id)
    with pytest.raises(BadRequest) as caught:
        await projects.seat_leader(project.id, second.id)

    assert caught.value.code == "role_seats_full"
    # Người ngồi trước vẫn ngồi, và câu trả lời "ai là Trưởng" không còn tuỳ thứ tự dòng.
    async with uow_factory() as uow:
        assert await leader_marius_id(uow, project.id) == first.id


async def test_the_bench_has_no_number_to_be_full_of(uow_factory) -> None:  # noqa: ANN001
    """Trần theo `seats` chỉ có nghĩa với một chỗ đã hứa với ai; chỗ ngồi chung thì không.

    Không có con số nào nói một dự án được hứa bao nhiêu người, nên chỗ ngồi chung không có
    gì để đầy.
    """
    ws = await WorkspaceService(uow_factory).create_workspace("WS")
    projects = ProjectService(uow_factory)
    project = await projects.create_project(ws.id, "Apollo", leader_description="Điều phối.")
    first, second = (await _agent(uow_factory, ws.id, "A"), await _agent(uow_factory, ws.id, "B"))

    await projects.add_member(project.id, first.id)
    await projects.add_member(project.id, second.id)

    seated = [
        g for g in await projects.list_seat_grants(project.id) if g.role_key == MEMBERS_ROLE_KEY
    ]
    assert len(seated) == 2


async def test_a_seat_given_back_frees_the_chair_again(uow_factory) -> None:  # noqa: ANN001
    """Đếm theo dòng đang sống, nên trả ghế là chỗ ấy trống thật."""
    ws = await WorkspaceService(uow_factory).create_workspace("WS")
    projects = ProjectService(uow_factory)
    project = await projects.create_project(ws.id, "Apollo", leader_description="Điều phối.")
    first, second = (await _agent(uow_factory, ws.id, "A"), await _agent(uow_factory, ws.id, "B"))

    await projects.seat_leader(project.id, first.id)
    await projects.revoke_seat_by_role(project.id, first.id, LEADER_ROLE_KEY, system=True)
    await projects.seat_leader(project.id, second.id)

    async with uow_factory() as uow:
        assert await leader_marius_id(uow, project.id) == second.id
