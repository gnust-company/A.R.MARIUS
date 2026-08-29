"""Ai đang gọi, và lượt chạy nào (T135 — FR-014g, FR-059, Điều I).

Trước đợt này, agent trình một token đúc một lần lúc nó được tạo ra và sống bằng cả đời nó.
Token ấy trả lời được **agent nào** và không trả lời được gì thêm — nên mọi cú ghi đi tới đều
không nói được nó sinh ra từ lượt chạy nào, đúng thứ FR-059 đòi. Nó cũng sống lâu hơn mọi lượt
chạy từng dùng nó, thứ FR-014b nói thẳng là không được.

Token của lượt chạy trả lời cả hai cùng lúc. Ba điều dưới đây là ba điều nó phải làm được, và
điều thứ ba là điều token cũ không bao giờ làm được:

  * lượt chạy còn mở thì đi lọt;
  * lượt chạy đã khép thì đọc thành **không tìm thấy**, không phải *bị cấm* — chuỗi đã chết và
    chuỗi chưa từng tồn tại trả lời y hệt nhau (Điều I);
  * cú ghi **mang danh tính lượt chạy**, nên với sang đầu việc khác là với vào chỗ không có.
"""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from armarius.infrastructure.adapters.echo import EchoAdapter
from armarius.infrastructure.database.engine import init_db
from armarius.main import app
from armarius.presentation.container import build_container
from tests.support.agents import invite_agent
from tests.support.runs import close_run, open_run
from tests.support.work import a_project, a_task

pytestmark = pytest.mark.anyio


@pytest.fixture(autouse=True)
async def _bootstrap():
    await init_db()
    container = build_container()
    container.registry.register(EchoAdapter(step_delay=0.0))
    app.state.container = container
    yield


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def _close(project_id) -> None:
    """Đóng một dự án ở tầng lưu trữ — bài này nói về phạm vi, không về cổng chuyển giai đoạn."""
    from armarius.domain.entities.project import ProjectStatus

    async with app.state.container.uow_factory() as uow:
        project = await uow.projects.get(project_id)
        assert project is not None
        project.status = ProjectStatus.CLOSED
        await uow.projects.update(project)
        await uow.commit()


async def _workspace(c: AsyncClient, email: str) -> tuple[dict, str]:
    registered = await c.post(
        "/auth/register",
        json={"email": email, "full_name": "Patron", "password": "password1234"},
    )
    assert registered.status_code == 201, registered.text
    headers = {"Authorization": f"Bearer {registered.json()['tokens']['access_token']}"}
    workspaces = await c.get("/v1/workspaces", headers=headers)
    return headers, workspaces.json()[0]["id"]


async def test_a_live_run_may_write_about_its_own_task() -> None:
    async with _client() as c:
        headers, ws_id = await _workspace(c, "live@armarius.dev")
        agent = await invite_agent(c, ws_id, headers)
        project_id = await a_project(ws_id)
        task_id = await a_task(project_id, assigned_to=agent["id"])
        run = await open_run(marius_id=agent["id"], task_id=task_id, project_id=project_id)

        said = await c.post(
            f"/agent/tasks/{task_id}/comment",
            headers=run.headers,
            json={"body": "Đang làm."},
        )
    assert said.status_code == 201, said.text


async def test_a_run_that_has_been_closed_writes_nothing_more() -> None:
    """FR-014b có một nửa dễ quên: thu hồi phải **có tác dụng**, không chỉ là xoá một cột.

    404 chứ không phải 403, và cùng một mã lý do với một chuỗi chưa từng tồn tại — ai cầm một
    token đã chết cũng không xác nhận được nó từng mở thứ gì (Điều I).
    """
    async with _client() as c:
        headers, ws_id = await _workspace(c, "closed@armarius.dev")
        agent = await invite_agent(c, ws_id, headers)
        project_id = await a_project(ws_id)
        task_id = await a_task(project_id, assigned_to=agent["id"])
        run = await open_run(marius_id=agent["id"], task_id=task_id, project_id=project_id)

        await close_run(run)

        refused = await c.post(
            f"/agent/tasks/{task_id}/comment",
            headers=run.headers,
            json={"body": "Vẫn còn nói được không?"},
        )
        invented = await c.get(
            "/agent/me", headers={"Authorization": "Bearer armr_run_khong-co-that"}
        )

    assert refused.status_code == 404, refused.text
    assert refused.json()["code"] == "run_not_found"
    assert invented.status_code == 404, invented.text
    assert invented.json()["code"] == refused.json()["code"], (
        "chuỗi đã chết và chuỗi chưa từng có phải đọc y hệt nhau"
    )


async def test_a_call_with_no_credential_at_all_is_a_different_answer() -> None:
    """Không trình gì cả thì chưa tới lượt hỏi *của ai* — 401, trước mọi luật."""
    async with _client() as c:
        bare = await c.get("/agent/me")
    assert bare.status_code == 401, bare.text
    assert bare.json()["code"] == "missing_bearer_token"


async def test_a_run_about_one_task_cannot_reach_another() -> None:
    """Đây là thứ token sống lâu không cấp được: nó không biết mình đang ở lượt chạy nào.

    Cùng một agent, cùng một workspace, cùng một dự án — chỉ khác đầu việc. Token cũ đi lọt cả
    hai vì nó chỉ trả lời *agent nào*; token của lượt chạy trả lời *lượt chạy nào*, nên đầu việc
    kia đọc thành không có (FR-059).
    """
    async with _client() as c:
        headers, ws_id = await _workspace(c, "scope@armarius.dev")
        agent = await invite_agent(c, ws_id, headers)
        project_id = await a_project(ws_id)
        mine = await a_task(project_id, assigned_to=agent["id"], title="Của tôi")
        theirs = await a_task(project_id, assigned_to=agent["id"], title="Không phải của tôi")
        run = await open_run(marius_id=agent["id"], task_id=mine, project_id=project_id)

        ok = await c.get(f"/agent/tasks/{mine}", headers=run.headers)
        reached = await c.post(
            f"/agent/tasks/{theirs}/comment",
            headers=run.headers,
            json={"body": "Tôi có nên ở đây không?"},
        )
        read = await c.get(f"/agent/tasks/{theirs}", headers=run.headers)

    assert ok.status_code == 200, ok.text
    assert reached.status_code == 404, reached.text
    assert reached.json()["code"] == "task_not_found"
    assert read.status_code == 404, "đọc cũng phải chặn: biết nó tồn tại đã là rò rồi"


async def test_a_run_about_a_project_may_still_work_across_its_tasks() -> None:
    """Trưởng dự án thức dậy ở **cấp dự án**, không kèm đầu việc nào — và vẫn phải chấm được việc.

    Một luật phạm vi viết đúng trên đường đang nhìn mà quên đường này sẽ khoá Trưởng dự án ra
    khỏi mọi đầu việc của chính dự án nó.
    """
    async with _client() as c:
        headers, ws_id = await _workspace(c, "leader@armarius.dev")
        agent = await invite_agent(c, ws_id, headers)
        project_id = await a_project(ws_id)
        one = await a_task(project_id, title="Một")
        two = await a_task(project_id, title="Hai")
        run = await open_run(marius_id=agent["id"], project_id=project_id)

        first = await c.get(f"/agent/tasks/{one}", headers=run.headers)
        second = await c.get(f"/agent/tasks/{two}", headers=run.headers)

    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text


async def test_a_run_about_one_project_cannot_reach_another() -> None:
    async with _client() as c:
        headers, ws_id = await _workspace(c, "twoprojects@armarius.dev")
        agent = await invite_agent(c, ws_id, headers)
        mine = await a_project(ws_id, name="Của tôi")
        theirs = await a_project(ws_id, name="Bên cạnh")
        run = await open_run(marius_id=agent["id"], project_id=mine)

        reached = await c.get(f"/agent/projects/{theirs}/queue", headers=run.headers)

    assert reached.status_code == 404, reached.text
    assert reached.json()["code"] == "project_not_found"


async def test_a_leader_run_cannot_reach_a_task_in_the_project_next_door() -> None:
    """So hai mã đầu việc là **không đủ**, và đây là đường mà một luật viết vội bỏ sót.

    Lượt chạy của Trưởng dự án không mang đầu việc nào — đó chính là điều làm nó hợp lệ trên
    mọi đầu việc của dự án nó. Nhưng nếu chỉ so đầu-việc-với-đầu-việc thì "không mang đầu việc
    nào" đọc thành "không có gì để so", và lượt chạy ấy với sang được đầu việc của dự án bên
    cạnh. `_leader_seat` bắt được ở bốn lối có hỏi nó và im ở mọi lối còn lại — bình luận, đổi
    trạng thái, công bố hiện vật đi lọt hết.
    """
    async with _client() as c:
        headers, ws_id = await _workspace(c, "nextdoor@armarius.dev")
        agent = await invite_agent(c, ws_id, headers)
        mine = await a_project(ws_id, name="Của tôi")
        theirs = await a_project(ws_id, name="Bên cạnh")
        their_task = await a_task(theirs, title="Việc bên cạnh")
        run = await open_run(marius_id=agent["id"], project_id=mine)

        wrote = await c.post(
            f"/agent/tasks/{their_task}/comment",
            headers=run.headers,
            json={"body": "Tôi ghi vào đây được không?"},
        )
        read = await c.get(f"/agent/tasks/{their_task}", headers=run.headers)

    assert wrote.status_code == 404, wrote.text
    assert wrote.json()["code"] == "task_not_found"
    assert read.status_code == 404, read.text


async def test_reaching_out_of_scope_never_answers_with_a_projects_state() -> None:
    """Lưới phạm vi phải chạy **trước** lưới dự án-đã-đóng, không phải sau.

    *Dự án này đã đóng* là một sự thật về một thứ người gọi có thể không có quyền biết là có
    tồn tại. Nếu lưới đóng chạy trước, một lượt chạy với sang đầu việc của dự án đã đóng sẽ
    nhận `409 project_closed` — và thế là nó vừa học được rằng đầu việc ấy có thật (Điều I).
    """
    async with _client() as c:
        headers, ws_id = await _workspace(c, "closedproject@armarius.dev")
        agent = await invite_agent(c, ws_id, headers)
        mine = await a_project(ws_id, name="Của tôi")
        my_task = await a_task(mine, assigned_to=agent["id"])
        theirs = await a_project(ws_id, name="Đã đóng")
        their_task = await a_task(theirs, title="Việc trong dự án đã đóng")
        await _close(theirs)
        run = await open_run(marius_id=agent["id"], task_id=my_task, project_id=mine)

        reached = await c.post(
            f"/agent/tasks/{their_task}/comment",
            headers=run.headers,
            json={"body": "Xin chào?"},
        )

    assert reached.status_code == 404, reached.text
    assert reached.json()["code"] == "task_not_found", (
        "trả lời bằng trạng thái của dự án bên cạnh là đã nói ra rằng nó có thật"
    )
