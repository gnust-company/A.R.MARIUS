"""Định tuyến mục chờ công nhận theo **người đã cấp agent vào ghế** (spec 001 FR-034, FR-035).

Trong phạm vi một người chủ (chốt 2026-08-03), người cấp ghế và chủ vùng làm việc luôn là
cùng một người — nên một bài kiểm chỉ nhìn "mục có tới đúng người không" sẽ **xanh dù luật
đi sai đường**. Vì vậy hai bài kiểm ở đây soi hai thứ khác nhau:

  1. Qua giao tiếp thật: cấp ghế xong thì ghế **có ghi người cấp**, và ghi đúng người bấm.
     Không ghi thì ngày mở nhiều người chủ, hệ thống không còn gì để tra.
  2. Dưới tầng giao tiếp: dựng một ghế mà người cấp **khác** chủ vùng — thứ chưa dựng được
     qua giao tiếp nhưng dựng được ở tầng lưu trữ — rồi kiểm mục chờ công nhận đi theo
     người cấp, không đi theo chủ vùng. Đây là chỗ duy nhất phân biệt được hai đường.
"""

from __future__ import annotations

from uuid import uuid4

import pytest

from armarius.domain.entities.inbox_item import InboxItemKind, InboxItemStatus
from armarius.domain.entities.seat_grant import SeatGrant
from tests.support.planning import client, operating_project


async def test_granting_a_seat_records_who_granted_it() -> None:
    """Quan hệ *ai cấp agent nào* phải được ghi ngay lúc cấp ghế, không suy lại sau."""
    async with client() as c:
        p = await operating_project(c, "route-a@armarius.dev")
        me = await c.get("/auth/me", headers=p.headers)
        assert me.status_code == 200, me.text
        my_id = str(me.json()["id"])

        seats = await c.get(f"/v1/projects/{p.project_id}/grants", headers=p.headers)
        assert seats.status_code == 200, seats.text
        rows = seats.json()

    assert rows, "dự án đang vận hành thì phải có ghế đã cấp"
    for row in rows:
        assert row["granted_by_user_id"] == my_id, row


async def test_the_acceptance_item_follows_the_seat_granter_not_the_workspace_owner(
    uow_factory,
) -> None:
    """Mục chờ công nhận đi theo **người cấp ghế**, kể cả khi người đó không phải chủ vùng.

    Đây là tình huống chưa dựng được qua giao tiếp (chưa có cơ chế mời người vào vùng làm
    việc), nhưng dựng được ở tầng lưu trữ — và nó là phép thử duy nhất phân biệt "tra theo
    người cấp ghế" với "suy thẳng từ chủ vùng". Ngày mở nhiều người chủ, đây là bài kiểm đã
    đứng sẵn.
    """
    from armarius.application.use_cases.approvals import ApprovalService

    owner_id = f"chu-vung-{uuid4()}"
    granter_id = f"nguoi-cap-ghe-{uuid4()}"
    project_id, task_id, _worker_id = await _seed_task_awaiting_acceptance(
        uow_factory, owner_user_id=owner_id, granted_by_user_id=granter_id
    )

    service = ApprovalService(uow_factory)
    recipient = await service.responsible_patron(task_id)
    assert recipient == granter_id, "phải tra ra người cấp ghế, không phải chủ vùng"
    assert recipient != owner_id

    async with uow_factory() as uow:
        placed = await uow.inbox.list_for_recipient(
            granter_id, status=InboxItemStatus.PENDING, project_id=project_id
        )
        stray = await uow.inbox.list_for_recipient(
            owner_id, status=InboxItemStatus.PENDING, project_id=project_id
        )
    assert [i.kind for i in placed] == [InboxItemKind.OUTPUT_ACCEPTANCE]
    assert stray == []


async def test_a_seat_with_no_granter_fails_loudly_instead_of_falling_back(
    uow_factory,
) -> None:
    """Ghế không ghi người cấp là dữ liệu hỏng, không phải chỗ để đoán.

    Rơi về chủ vùng cho "chạy được" là đúng thứ sẽ im lặng làm sai ngày có nhiều người chủ.
    """
    from armarius.application.use_cases.approvals import ApprovalService, ResponsiblePatronUnknown

    owner_id = f"chu-vung-{uuid4()}"
    _project_id, task_id, _worker_id = await _seed_task_awaiting_acceptance(
        uow_factory, owner_user_id=owner_id, granted_by_user_id=None, place_inbox=False
    )

    service = ApprovalService(uow_factory)
    with pytest.raises(ResponsiblePatronUnknown):
        await service.responsible_patron(task_id)


# ── dựng dữ liệu ────────────────────────────────────────────────────────────


async def _seed_task_awaiting_acceptance(
    uow_factory,
    *,
    owner_user_id: str,
    granted_by_user_id: str | None,
    place_inbox: bool = True,
) -> tuple[object, object, object]:
    """Một vùng làm việc của `owner_user_id`, một dự án, một ghế do `granted_by_user_id`
    cấp, và một đầu việc đang *chờ rà soát* do agent ngồi ghế đó phụ trách."""
    from armarius.domain.entities.marius import Marius
    from armarius.domain.entities.project import Project
    from armarius.domain.entities.role import Role
    from armarius.domain.entities.task import Task, TaskStatus
    from armarius.domain.entities.workspace import Workspace

    async with uow_factory() as uow:
        ws = await uow.workspaces.add(
            Workspace(name="WS", slug=f"ws-{uuid4().hex[:8]}", owner_user_id=owner_user_id)
        )
        project = await uow.projects.add(
            Project(workspace_id=ws.id, name="P", slug=f"p-{uuid4().hex[:8]}", key="PR")
        )
        await uow.commit()
        role = await uow.roles.add(
            Role(project_id=project.id, key="backend", title="Backend", seats=1)
        )
        worker = await uow.mariuses.add(
            Marius(workspace_id=ws.id, name=f"Dev-{uuid4().hex[:6]}", adapter_type="echo")
        )
        await uow.commit()
        await uow.seat_grants.add(
            SeatGrant(
                project_id=project.id,
                role_id=role.id,
                marius_id=worker.id,
                granted_by_user_id=granted_by_user_id,
            )
        )
        task = await uow.tasks.add(
            Task(
                project_id=project.id,
                title="Kết xuất báo cáo",
                description="Gom số liệu rồi kết xuất.",
                status=TaskStatus.IN_REVIEW,
                assigned_marius_id=worker.id,
            )
        )
        await uow.commit()
        project_id, task_id, worker_id = project.id, task.id, worker.id

    if place_inbox:
        from armarius.application.use_cases.approvals import ApprovalService

        await ApprovalService(uow_factory).sign_as_leader(
            task_id, marius_id=uuid4(), approve=True
        )
    return project_id, task_id, worker_id
