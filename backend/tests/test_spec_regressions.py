"""Regression guards for requirements that were right, but unwatched (T161).

Đợt 9 rà lại và tìm ra một nhóm yêu cầu **đang đúng trong mã mà không bài kiểm nào canh**.
Đúng-mà-không-ai-canh không phải là an toàn: nó chỉ có nghĩa là ngày một đợt sau làm hỏng,
bộ kiểm vẫn xanh và không ai biết cho tới lúc người dùng gặp.

Mỗi bài dưới đây gắn tên vào **một** yêu cầu và kiểm đúng cái yêu cầu đó nói. Chúng cố ý
ngắn: bài kiểm hồi quy chỉ có một việc — hỏng lên đỏ, và nói ngay đỏ vì điều gì.

Ghi chú trung thực về phạm vi: trong mười bốn yêu cầu ban đầu ghi ở T161, khảo sát lại
thấy **bốn** yêu cầu (FR-025, FR-026, FR-032, FR-046) đã có bài kiểm ở chỗ khác —
``test_task_dependencies``, ``test_task_rules``, ``test_wake_prompt``. Chúng không được
chép lại ở đây; danh sách trong ``tasks.md`` đã sửa cho khớp.
"""

from __future__ import annotations

from uuid import uuid4

import pytest

from armarius.domain.entities.marius import Marius
from armarius.domain.entities.run import WakeSource
from armarius.domain.entities.task import Task, TaskStatus
from armarius.domain.services.wake_prompt import WakeContext, build_wake_prompt
from armarius.infrastructure.adapters.echo import EchoAdapter
from armarius.infrastructure.database.engine import init_db
from armarius.main import app
from armarius.presentation.container import build_container
from tests.support.agents import invite_and_online
from tests.support.planning import client, operating_project, register
from tests.support.projects import force_operating


@pytest.fixture(autouse=True)
async def _bootstrap():
    await init_db()
    container = build_container()
    container.registry.register(EchoAdapter(step_delay=0.0))
    app.state.container = container
    yield


async def _live_task(c, p, *, title: str = "Đầu việc") -> str:
    """A task on the board of an operating project, created in-scope of the plan."""
    r = await c.post(
        f"/v1/projects/{p.project_id}/tasks",
        headers=p.headers,
        json={"title": title, "description": "Làm cho xong phần này."},
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


# ── D. Đầu việc — bộ trường ──────────────────────────────────────────────────────


async def test_fr016_the_identifier_never_changes_for_the_life_of_the_task():
    """FR-016 — mã định danh sinh từ *tiền tố dự án + số thứ tự*, và **bất biến**.

    Sinh đúng lúc tạo đã có bài kiểm; *bất biến* thì chưa. Mã này là thứ người ta gọi tên
    đầu việc trong tin nhắn, trong nhật ký và trong hồ sơ leo thang — một mã đổi giữa
    chừng biến mọi câu đã nói về nó thành câu nói về một đầu việc không còn tồn tại.
    """
    async with client() as c:
        p = await operating_project(c, "fr016@armarius.dev", name="Apollo")
        task_id = await _live_task(c, p)
        first = (await c.get(f"/v1/tasks/{task_id}", headers=p.headers)).json()
        assert first["identifier"], "đầu việc phải có mã ngay khi tạo"
        assert first["identifier"].startswith("APOL")

        # Đẩy nó qua đủ thứ có thể đụng vào bản ghi: đổi người, đổi trạng thái, đổi tiêu chí.
        await c.post(
            f"/v1/tasks/{task_id}/assign",
            headers=p.headers,
            json={"marius_id": p.worker_id},
        )
        await c.post(
            f"/v1/tasks/{task_id}/status", headers=p.headers, json={"status": "todo"}
        )
        await c.put(
            f"/v1/tasks/{task_id}/criteria",
            headers=p.headers,
            json={"items": [{"text": "Chạy được"}]},
        )
        after = (await c.get(f"/v1/tasks/{task_id}", headers=p.headers)).json()
        assert after["identifier"] == first["identifier"]


async def test_fr017_a_task_carries_exactly_one_assignee_at_a_time():
    """FR-017 — đúng **một** người phụ trách tại mọi thời điểm.

    Kiểm ở tầng dữ liệu, không phải tầng cổng chặn: một chuyển giao hợp lệ **thay** người
    chứ không **thêm** người. Đây là điều FR-028 bảo vệ từ phía cổng, và là điều còn lại
    sau khi cổng đã cho qua.
    """
    async with client() as c:
        p = await operating_project(c, "fr017@armarius.dev")
        task_id = await _live_task(c, p)
        second_id, _ = await invite_and_online(
            c, p.workspace_id, p.headers, name="Dev2"
        )

        first = await c.post(
            f"/v1/tasks/{task_id}/assign",
            headers=p.headers,
            json={"marius_id": p.worker_id},
        )
        assert first.json()["assigned_marius_id"] == p.worker_id

        moved = await c.post(
            f"/v1/tasks/{task_id}/assign",
            headers=p.headers,
            json={"marius_id": second_id, "transfer_reason": "Dev nghỉ phép"},
        )
        assert moved.status_code == 200, moved.text
        # Người mới **thế chỗ** — không có chỗ nào giữ cả hai.
        assert moved.json()["assigned_marius_id"] == second_id


async def test_fr020_the_next_action_travels_in_the_wake_packet() -> None:
    """FR-020 — *việc kế tiếp* lưu bền và **trả lại kèm gói tin** mỗi lần gọi dậy.

    Lưu được mà không gửi kèm thì agent mở mắt ra không biết mình đang dở việc gì, và làm
    lại từ đầu — đúng thứ trường này sinh ra để tránh.
    """
    task = Task(
        title="Dựng cổng đăng nhập",
        description="Xong phần máy chủ",
        status=TaskStatus.IN_PROGRESS,
        next_action="Còn thiếu bài kiểm cho đường thất bại",
    )
    prompt = build_wake_prompt(
        WakeContext(
            marius_name="Dev",
            task_title=task.title,
            task_status=str(task.status),
            task_description=task.description,
            next_action=task.next_action,
            directory=[],
            new_messages=[],
            source=WakeSource.CONTINUATION,
            reason="Việc còn dở, làm tiếp",
        )
    )
    assert "Còn thiếu bài kiểm cho đường thất bại" in prompt

    # Mặt kia của cùng một luật: đầu việc không có phần dở thì gói tin không được mang
    # theo phần dở của ai khác.
    blank = build_wake_prompt(
        WakeContext(
            marius_name="Dev",
            task_title=task.title,
            task_status=str(task.status),
            task_description=task.description,
            next_action=None,
            directory=[],
            new_messages=[],
            source=WakeSource.ASSIGNMENT,
            reason="Vừa được giao",
        )
    )
    assert "Còn thiếu bài kiểm cho đường thất bại" not in blank


# ── E. Đầu việc — vòng đời và cổng chặn ──────────────────────────────────────────


async def test_fr023_a_refused_move_leaves_the_task_exactly_where_it_was():
    """FR-023 — chuyển trạng thái sai bị từ chối, **giữ nguyên trạng thái cũ**, nêu lý do.

    Bảng chuyển trạng thái đã có bài kiểm ở tầng thực thể. Điều chưa ai canh là nửa sau
    của câu: qua đường HTTP thật, một lần từ chối không được để lại đầu việc ở đâu đó
    giữa chừng. Một cổng chặn mà vẫn ghi mất nửa thay đổi thì tệ hơn không có cổng.
    """
    async with client() as c:
        p = await operating_project(c, "fr023@armarius.dev")
        task_id = await _live_task(c, p)

        refused = await c.post(
            f"/v1/tasks/{task_id}/status", headers=p.headers, json={"status": "done"}
        )
        assert refused.status_code >= 400, refused.text
        assert refused.json()["detail"], "từ chối phải kèm lý do đọc được"

        still = await c.get(f"/v1/tasks/{task_id}", headers=p.headers)
        assert still.json()["status"] == "backlog"


async def test_fr028_a_second_person_cannot_be_added_to_a_task():
    """FR-028 *(cổng một-người)* — gán người thứ hai bị **từ chối**.

    Không phải "được nhưng ghi đè im lặng": lời từ chối phải nói ra hai lối đi hợp lệ,
    vì người bấm nút gần như luôn định làm một trong hai.
    """
    async with client() as c:
        p = await operating_project(c, "fr028@armarius.dev")
        task_id = await _live_task(c, p)
        second_id, _ = await invite_and_online(
            c, p.workspace_id, p.headers, name="Dev2"
        )

        await c.post(
            f"/v1/tasks/{task_id}/assign",
            headers=p.headers,
            json={"marius_id": p.worker_id},
        )
        refused = await c.post(
            f"/v1/tasks/{task_id}/assign",
            headers=p.headers,
            json={"marius_id": second_id},
        )
        assert refused.status_code == 409, refused.text
        assert refused.json()["code"] == "task_already_assigned", refused.text

        # Người cũ vẫn giữ việc — lời từ chối không được làm rơi mất người phụ trách.
        still = await c.get(f"/v1/tasks/{task_id}", headers=p.headers)
        assert still.json()["assigned_marius_id"] == p.worker_id


# ── G. Đánh thức ────────────────────────────────────────────────────────────────


async def test_fr051_what_the_agent_leaves_behind_is_kept():
    """FR-051 — trước khi kết thúc lượt, agent để lại *việc kế tiếp*; hệ thống **lưu bền**.

    Nối liền với FR-020: một bên ghi, một bên đọc. Nếu bên ghi rơi thì bên đọc luôn thấy
    "không có", và không ai phát hiện ra vì "không có" là một câu trả lời hợp lệ.
    """
    async with client() as c:
        p = await operating_project(c, "fr051@armarius.dev")
        task_id = await _live_task(c, p)
        await c.post(
            f"/v1/tasks/{task_id}/assign",
            headers=p.headers,
            json={"marius_id": p.worker_id},
        )
        left = await c.post(
            f"/agent/tasks/{task_id}/next-action",
            headers=p.worker_headers,
            json={"next_action": "Bóng đang ở chỗ người rà soát"},
        )
        assert left.status_code == 200, left.text

        reread = await c.get(f"/v1/tasks/{task_id}", headers=p.headers)
        assert reread.json()["next_action"] == "Bóng đang ở chỗ người rà soát"


# ── J. Ranh giới vai trò và quyền hạn ───────────────────────────────────────────


async def test_fr070_the_patron_can_do_what_the_leader_can_do():
    """FR-070 — người chủ can thiệp trực tiếp ở mức tương đương Trưởng dự án.

    Đây là **quyền, không phải nghĩa vụ** — nên bài kiểm không hỏi người chủ có làm không,
    chỉ hỏi mỗi lối có mở không: bình luận, giao việc, đổi ưu tiên, bố trí thợ.
    """
    async with client() as c:
        p = await operating_project(c, "fr070@armarius.dev")
        task_id = await _live_task(c, p)

        said = await c.post(
            f"/v1/tasks/{task_id}/comments",
            headers=p.headers,
            json={"body": "Ưu tiên phần này trước.", "author_kind": "human"},
        )
        assert said.status_code == 201, said.text

        gave = await c.post(
            f"/v1/tasks/{task_id}/assign",
            headers=p.headers,
            json={"marius_id": p.worker_id},
        )
        assert gave.status_code == 200, gave.text
        assert gave.json()["assigned_marius_id"] == p.worker_id

        listed = await c.get(f"/v1/projects/{p.project_id}/agents", headers=p.headers)
        assert listed.status_code == 200, listed.text


async def test_fr073_the_system_never_signs_for_anyone():
    """FR-073 — hệ thống KHÔNG tự duyệt, tự công nhận, tự chọn thợ.

    Kiểm bằng cách bỏ đói nó: một đầu việc có thành phẩm, không ai ký, và **không** được
    tự đóng. Hai chữ ký là hai người quyết; một hệ thống điền hộ chữ ký thứ hai để bảng
    trông sạch là một hệ thống nói dối về ai đã chịu trách nhiệm.
    """
    async with client() as c:
        p = await operating_project(c, "fr073@armarius.dev")
        task_id = await _live_task(c, p)
        await c.post(
            f"/v1/tasks/{task_id}/assign",
            headers=p.headers,
            json={"marius_id": p.worker_id},
        )
        await c.post(
            f"/v1/tasks/{task_id}/status",
            headers=p.headers,
            json={"status": "in_progress"},
        )
        await c.post(
            f"/v1/tasks/{task_id}/artifacts",
            headers=p.headers,
            json={"name": "ket-qua.md", "kind": "note", "content": "xong"},
        )
        await c.post(
            f"/v1/tasks/{task_id}/status", headers=p.headers, json={"status": "in_review"}
        )

        signatures = await c.get(f"/v1/tasks/{task_id}/approvals", headers=p.headers)
        assert signatures.status_code == 200
        assert signatures.json() == [], "không ai ký thì bảng chữ ký phải trống"

        state = await c.get(f"/v1/tasks/{task_id}", headers=p.headers)
        assert state.json()["status"] == "in_review", "không được tự nhảy sang *xong*"


async def test_fr078_the_two_way_channel_and_the_board_both_exist():
    """FR-078 — một kênh đối thoại hai chiều với Trưởng dự án, **và** một bảng dự án.

    Hai mặt, một yêu cầu: nói được với Trưởng dự án, và nhìn được toàn cảnh mà không phải
    hỏi nó. Có mặt này mà thiếu mặt kia là quay lại chỗ mọi câu hỏi đều tốn một lượt agent.
    """
    async with client() as c:
        p = await operating_project(c, "fr078@armarius.dev")
        await _live_task(c, p)

        room = await c.get(f"/v1/projects/{p.project_id}/leader-chat", headers=p.headers)
        assert room.status_code == 200, room.text
        room_body = room.json()
        assert "transcript" in room_body
        assert room_body["leader_marius_id"] == p.leader_id
        # Hai chiều: người chủ nói được vào, không chỉ đọc ra.
        said = await c.post(
            f"/v1/projects/{p.project_id}/leader-chat/messages",
            headers=p.headers,
            json={"message": "Tiến độ thế nào?"},
        )
        assert said.status_code in (200, 202), said.text

        board = await c.get(f"/v1/projects/{p.project_id}/tasks", headers=p.headers)
        assert board.status_code == 200, board.text
        assert len(board.json()) >= 1
        assert {"status", "title", "identifier"} <= set(board.json()[0])


async def test_fr082_one_agent_two_projects_two_roles():
    """FR-082 — ngữ cảnh lấy theo vai trong **dự án** đang làm, không theo workspace.

    Cùng một con agent, hai dự án, hai vai. Nếu vai bị đọc từ tầng workspace thì hai gói
    tin sẽ giống hệt nhau và agent sẽ mang vai của dự án kia sang dự án này.
    """
    async with client() as c:
        h, ws_id = await register(c, "fr082@armarius.dev")
        marius_id, _ = await invite_and_online(c, ws_id, h, name="Đa-năng")

        made = []
        for name, role_title in (("Alpha", "Backend"), ("Beta", "Frontend")):
            role_desc = f"Lo phần {role_title} của dự án {name}."
            created = await c.post(
                f"/v1/workspaces/{ws_id}/projects",
                headers=h,
                json={
                    "name": name,
                    "objective": f"Mục tiêu {name}",
                    "leader": {"description": "Điều phối.", "marius_id": None},
                    "roles": [
                        {"title": role_title, "seats": 1, "description": role_desc}
                    ],
                },
            )
            assert created.status_code == 201, created.text
            pid = created.json()["id"]
            await force_operating(pid)
            granted = await c.post(
                f"/v1/projects/{pid}/grant",
                headers=h,
                json={"role_key": role_title.lower(), "marius_id": marius_id},
            )
            assert granted.status_code == 201, granted.text
            made.append((pid, role_title.lower()))

        seen = []
        for pid, expected_role in made:
            seats = await c.get(f"/v1/projects/{pid}/agents", headers=h)
            assert seats.status_code == 200, seats.text
            mine = [s for s in seats.json() if s["marius_id"] == marius_id]
            assert len(mine) == 1, seats.text
            # Vai đọc ra phải là vai **của dự án này** — không phải một thuộc tính chung
            # dính vào con agent ở tầng workspace.
            assert mine[0]["role_key"] == expected_role
            seen.append(mine[0]["role_key"])
        # Và hai vai phải **khác nhau**: nếu chúng giống nhau thì bài kiểm ở trên vẫn xanh
        # với một vai đọc từ tầng workspace, và không kiểm được gì cả.
        assert seen[0] != seen[1]


async def test_fr082_the_marius_entity_carries_no_project_role() -> None:
    """Cùng một luật, kiểm từ phía dữ liệu: nếu vai sống trên chính con agent thì nó chỉ
    có **một** vai, và mọi thứ ở trên là ảo giác. Chỗ duy nhất giữ vai là cái ghế dự án."""
    marius = Marius(workspace_id=uuid4(), name="Đa-năng")
    assert not hasattr(marius, "project_role")
    assert not hasattr(marius, "role_description")
