"""Dự án đóng là đóng băng — mọi lối ghi đều dừng (spec 001 FR-005).

Người chủ chốt 2026-08-16: *"đóng dự án là như kiểu đóng băng, không thao tác gì được nữa
cả, tất cả lối vào dự án đó — nộp, sửa, đổi vai, đổi kế hoạch — tất tần tật không làm được"*.

Bài kiểm đầu tiên trong tệp này là bài quan trọng nhất: nó **duyệt cả bảng đường dẫn** và
bắt lỗi nếu có một lối ghi nào chạm tới dự án mà không đi qua chỗ chặn. Không có nó thì
luật này đúng đúng một hôm, tới khi ai đó thêm một lối mới rồi quên.

Bản đầu của bài kiểm ấy chỉ soi những lối có `{project_id}` hoặc `{task_id}` trong đường
dẫn — tức là nó dùng đúng cái giả định mà chỗ chặn dùng, nên nó mù đúng chỗ chỗ chặn mù.
Lối trả lời thư leo thang (`POST /v1/inbox/{item_id}/answer`) không mang tên nào trong hai
tên đó, mà bấm vào thì giao lại người / huỷ / đặt bước tiếp cho đầu việc — nó ghi được vào
dự án đã đóng, và bài kiểm không hề thấy. Nên giờ bài kiểm duyệt **mọi** lối ghi trong hệ
thống: hoặc có chốt, hoặc phải nằm trong một danh sách miễn viết tay có ghi lý do.
"""

from __future__ import annotations

from uuid import UUID, uuid4

from httpx import ASGITransport, AsyncClient

from armarius.domain.entities.inbox_item import InboxItemKind
from armarius.domain.entities.project import ProjectStatus
from armarius.main import app
from armarius.presentation.api.frozen import refuse_when_frozen
from tests.support.projects import force_operating, force_phase

_READ_ONLY = {"GET", "HEAD", "OPTIONS"}

# Lối ghi **không gắn chốt**, mỗi lối một lý do. Danh sách viết tay là chủ ý: thêm một lối
# ghi mới thì hoặc nó có chốt, hoặc người thêm phải xuống đây viết ra vì sao nó không cần —
# không có đường thứ ba, và không có cách nào lọt vì đặt tên đường dẫn khác đi.
#
# Đây không phải chỗ ghi ngoại lệ *bên trong* chốt: xoá cả dự án vẫn đi qua chốt và được
# chốt tự cho qua, nên nó không nằm đây — `test_a_closed_project_can_still_be_thrown_away`
# mới là bài canh chuyện đó.
_NEEDS_NO_GUARD: dict[tuple[str, str], str] = {
    # Đăng nhập, đăng ký, làm mới phiên — chưa dính tới dự án nào.
    ("POST", "/auth/login"): "chưa có dự án nào trong tầm",
    ("POST", "/auth/refresh"): "chưa có dự án nào trong tầm",
    ("POST", "/auth/register"): "chưa có dự án nào trong tầm",
    # Buổi dựng đội: dự án chưa ra đời, kết thúc buổi mới sinh ra nó.
    ("POST", "/v1/onboarding/{session_id}/abandon"): "dự án chưa ra đời",
    ("POST", "/v1/onboarding/{session_id}/answer"): "dự án chưa ra đời",
    ("POST", "/v1/onboarding/{session_id}/finalize"): "dự án chưa ra đời",
    ("POST", "/v1/workspaces/{workspace_id}/onboarding"): "dự án chưa ra đời",
    # Không gian làm việc, người thợ, nhãn, bộ kỹ năng — sống trên một tầng trên dự án và
    # dùng chung cho mọi dự án trong đó, nên một dự án đóng không đông cứng chúng.
    ("POST", "/v1/workspaces"): "tầng trên dự án",
    ("PATCH", "/v1/workspaces/{workspace_id}"): "tầng trên dự án",
    ("DELETE", "/v1/workspaces/{workspace_id}"): "tầng trên dự án",
    ("POST", "/v1/workspaces/{workspace_id}/labels"): "tầng trên dự án",
    ("POST", "/v1/workspaces/{workspace_id}/mariuses"): "tầng trên dự án",
    ("PATCH", "/v1/workspaces/{workspace_id}/mariuses/{marius_id}"): "tầng trên dự án",
    ("DELETE", "/v1/workspaces/{workspace_id}/mariuses/{marius_id}"): "tầng trên dự án",
    ("POST", "/v1/workspaces/{workspace_id}/mariuses/{marius_id}/designate"): "tầng trên dự án",
    (
        "POST",
        "/v1/workspaces/{workspace_id}/mariuses/{marius_id}/install-skills",
    ): "tầng trên dự án",
    ("POST", "/v1/workspaces/{workspace_id}/skills/import"): "tầng trên dự án",
    ("POST", "/v1/workspaces/{workspace_id}/skills/manual"): "tầng trên dự án",
    ("PUT", "/v1/workspaces/{workspace_id}/skills/{skill_id}"): "tầng trên dự án",
    ("DELETE", "/v1/workspaces/{workspace_id}/skills/{skill_id}"): "tầng trên dự án",
    # Nối máy vào workspace và giữ token của máy: cùng một tầng trên dự án, và còn cao hơn
    # nữa — lúc gọi hai lối đầu thì máy chưa thuộc về workspace nào, nên chẳng có dự án nào
    # để mà hỏi. Một dự án đóng lại không được ngăn người ta cắm thêm máy.
    ("POST", "/daemon/link/start"): "tầng trên dự án",
    ("POST", "/daemon/link/poll"): "tầng trên dự án",
    ("POST", "/daemon/token/renew"): "tầng trên dự án",
    ("POST", "/v1/machines/link/{code}/approve"): "tầng trên dự án",
    # Chỗ làm và nhịp sống của máy: thuộc về cái máy và không gian làm việc, không
    # thuộc dự án nào. Một dự án đóng lại không được làm máy tưởng mình mất kết nối.
    ("PUT", "/daemon/workplaces"): "tầng trên dự án",
    ("POST", "/daemon/heartbeat"): "tầng trên dự án",
    # Xin việc và báo đã chạy: chốt nằm **trong**, không nằm ở cửa. Một cú xin không nói về
    # một dự án nào cả — nó là một cái máy hỏi về mọi thứ nó đang chứa — nên chặn cả cú xin
    # vì một đầu việc thuộc dự án đã đóng là đóng băng luôn phần việc không liên quan trên
    # cùng cái máy. Câu lệnh lấy việc tự loại đầu việc của dự án đã đóng ra khỏi kệ.
    ("POST", "/daemon/runs/claim"): "chốt nằm trong câu lệnh lấy việc, không ở cửa",
    ("POST", "/daemon/runs/{run_id}/start"): "chốt nằm trong câu lệnh lấy việc, không ở cửa",
    # The two inbox doors: the guard is enforced **inside** rather than at the door,
    # because one path carries both an action that writes into the project and one that
    # only tidies the patron's own inbox — and which it is lives in the request body, read
    # after routing has already happened. Held by
    # `test_a_letter_on_a_closed_project_refuses_only_what_touches_the_task`.
    ("POST", "/v1/inbox/{item_id}/answer"): "chốt nằm trong, theo từng loại câu trả lời",
    ("POST", "/v1/inbox/{item_id}/resolve"): "chỉ dọn hộp thư, không ghi vào dự án",
}


def _is_guarded(dependant: object) -> bool:
    """True nếu chỗ chặn nằm đâu đó trong chuỗi phụ thuộc của lối này.

    Đọc chuỗi đã dựng chứ không đọc danh sách khai báo: gắn ở bộ định tuyến, ở lối, hay
    lồng trong một phụ thuộc khác đều tính — điều cần canh là *nó có chạy hay không*.
    """
    if dependant is None:
        return False
    if getattr(dependant, "call", None) is refuse_when_frozen:
        return True
    return any(
        _is_guarded(child) for child in getattr(dependant, "dependencies", []) or []
    )


def _write_routes() -> list[tuple[str, str, object]]:
    """Mọi lối ghi trong hệ thống, không lọc theo hình dạng đường dẫn."""
    found = []
    for route in app.routes:
        writes = (getattr(route, "methods", None) or set()) - _READ_ONLY
        if writes:
            found.append(
                (sorted(writes)[0], getattr(route, "path", ""), getattr(route, "dependant", None))
            )
    return found


def test_no_write_route_escapes_the_guard_without_a_written_reason() -> None:
    escaped = [
        f"{method} {path}"
        for method, path, dependant in _write_routes()
        if not _is_guarded(dependant) and (method, path) not in _NEEDS_NO_GUARD
    ]
    assert not escaped, (
        "mấy lối ghi này không qua chốt đóng băng và cũng không có lý do được miễn — "
        "gắn chốt cho chúng, hoặc thêm vào _NEEDS_NO_GUARD kèm lý do: " + ", ".join(escaped)
    )


def test_the_exemption_list_has_no_stale_entries() -> None:
    """Một dòng miễn còn nằm đó sau khi lối ấy đã có chốt là lời nói dối để lại trong tệp —
    người đọc sau tưởng lối đó vẫn hở, hoặc tệ hơn, tưởng miễn là chuyện thường."""
    live = {(m, p) for m, p, _ in _write_routes()}
    guarded = {(m, p) for m, p, d in _write_routes() if _is_guarded(d)}
    assert not (_NEEDS_NO_GUARD.keys() & guarded), "đã có chốt rồi thì bỏ khỏi danh sách miễn"
    assert not (_NEEDS_NO_GUARD.keys() - live), "danh sách miễn còn ghi lối không còn tồn tại"


def test_the_audit_above_can_actually_fail() -> None:
    """Một bài duyệt luôn xanh thì vô dụng. Chứng minh phép đọc chuỗi phụ thuộc phân biệt
    được lối có chặn và lối không — nếu không, bài trên xanh vì nó không nhìn thấy gì."""
    guarded = [
        r for r in app.routes
        if "{task_id}" in getattr(r, "path", "")
        and _is_guarded(getattr(r, "dependant", None))
    ]
    bare = [
        r for r in app.routes
        if getattr(r, "path", "") == "/healthz"
        and not _is_guarded(getattr(r, "dependant", None))
    ]
    assert guarded, "phép đọc không thấy chỗ chặn ở đâu cả"
    assert bare, "phép đọc thấy chỗ chặn cả ở lối không hề có"


# ── và luật đó đúng qua đường truyền thật ──────────────────────────────────────────


async def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def _register(c: AsyncClient, email: str) -> tuple[dict, str]:
    r = await c.post(
        "/auth/register",
        json={"email": email, "full_name": "Patron", "password": "password1234"},
    )
    headers = {"Authorization": f"Bearer {r.json()['tokens']['access_token']}"}
    ws = await c.get("/v1/workspaces", headers=headers)
    return headers, ws.json()[0]["id"]


async def _live_project_with_a_task(c: AsyncClient, ws: str, h: dict) -> tuple[str, str]:
    proj = await c.post(
        f"/v1/workspaces/{ws}/projects",
        headers=h,
        json={
            "name": "Apollo",
            "key": "APO",
            "leader": {"description": "Leads.", "marius_id": None},
            "roles": [{"title": "Backend", "seats": 1, "description": "Owns the API."}],
        },
    )
    pid = proj.json()["id"]
    await force_operating(pid)
    task = await c.post(
        f"/v1/projects/{pid}/tasks",
        headers=h,
        json={"title": "Xuất báo cáo", "description": "Gom số liệu rồi kết xuất."},
    )
    return pid, task.json()["id"]


async def test_every_kind_of_write_is_refused_once_the_project_is_closed() -> None:
    """Sáu lối khác nhau, sáu tầng khác nhau — cùng một câu trả lời.

    Chọn đúng những lối trước đây vẫn ghi được sau khi đóng: bình luận, nộp thành phẩm,
    đổi trạng thái, đặt tiêu chí, thêm vai, đổi ngưỡng.
    """
    async with await _client() as c:
        h, ws = await _register(c, "frozen1@example.com")
        pid, tid = await _live_project_with_a_task(c, ws, h)
        await force_phase(app.state.container.uow_factory, pid, ProjectStatus.CLOSED)

        attempts = {
            "bình luận": c.post(
                f"/v1/tasks/{tid}/comments", headers=h, json={"body": "một lời"}
            ),
            "nộp thành phẩm": c.post(
                f"/v1/tasks/{tid}/artifacts",
                headers=h,
                json={"name": "bao-cao.xlsx", "kind": "file", "uri": "s3://x/y"},
            ),
            "đổi trạng thái": c.post(
                f"/v1/tasks/{tid}/status", headers=h, json={"status": "todo"}
            ),
            "đặt tiêu chí": c.put(
                f"/v1/tasks/{tid}/criteria", headers=h, json={"items": ["xong"]}
            ),
            "thêm vai": c.post(
                f"/v1/projects/{pid}/roles",
                headers=h,
                json={"key": "qa", "title": "QA", "seats": 1, "description": "Kiểm."},
            ),
            "đổi ngưỡng": c.put(
                f"/v1/projects/{pid}/thresholds", headers=h, json={"level1_attempts": 5}
            ),
            "tạo đầu việc mới": c.post(
                f"/v1/projects/{pid}/tasks", headers=h, json={"title": "Việc mới"}
            ),
            "sửa đầu việc": c.patch(
                f"/v1/tasks/{tid}", headers=h, json={"title": "Tên khác"}
            ),
        }
        for label, coro in attempts.items():
            r = await coro
            assert r.status_code == 409, f"{label} vẫn ghi được: {r.status_code} {r.text}"


async def test_a_letter_on_a_closed_project_refuses_only_what_touches_the_task() -> None:
    """The door the first version let through: an escalation letter in the patron's inbox.

    A real scenario — a task in progress goes quiet, climbs to the patron as a letter; the
    patron closes the project (no rule stops them closing with letters outstanding); then
    goes to the inbox and presses *reassign*. Before the fix that call really ran, waking
    somebody new for a project already declared finished. Its URL carries only the letter
    id, so both the guard and the path-shaped audit looked straight through it.

    But only the three buttons that write to the task should die. The first fix froze the
    **close the letter** button too, which writes nothing into the project — leaving a
    letter that could never leave the waiting list. This holds that exact line.

    Closed at the storage layer rather than through the phase route, so the letter stays
    *pending*: precisely the narrow window the phase route's sweep does not cover.
    """
    async with await _client() as c:
        h, ws = await _register(c, "frozen5@example.com")
        pid, tid = await _live_project_with_a_task(c, ws, h)

        me = (await c.get("/auth/me", headers=h)).json()
        letter = await app.state.container.inbox.place(
            workspace_id=UUID(ws),
            recipient_user_id=str(me["id"]),
            kind=InboxItemKind.ESCALATION,
            title="Đầu việc đứng khựng",
            project_id=UUID(pid),
            task_id=UUID(tid),
        )
        await force_phase(app.state.container.uow_factory, pid, ProjectStatus.CLOSED)

        for label, body in {
            "giao lại người khác": {"answer": "reassign", "marius_id": str(uuid4())},
            "đặt bước tiếp theo": {"answer": "next_action", "text": "thử lại"},
            "huỷ đầu việc": {"answer": "cancel", "text": "thôi"},
        }.items():
            r = await c.post(f"/v1/inbox/{letter.id}/answer", headers=h, json=body)
            assert r.status_code == 409, f"{label} vẫn chạy: {r.status_code} {r.text}"

        # Still readable — the letter stays where it is.
        listed = await c.get("/v1/inbox", headers=h)
        assert str(letter.id) in {i["id"] for i in listed.json()}

        # …and the patron can still clear it. Without this the letter is stuck for ever.
        r = await c.post(f"/v1/inbox/{letter.id}/resolve", headers=h)
        assert r.status_code == 200, r.text
        assert r.json()["status"] == "resolved"


async def test_closing_a_project_retires_every_letter_it_leaves_open() -> None:
    """Closing a project closes the questions it leaves outstanding (FR-005).

    A question about a closed project is a question that can never be answered — all three
    decision buttons are refused from here on. Leaving it in the waiting list means a count
    that never comes down, and a reminder ladder chasing an answer the system itself
    forbids.

    Marked *void*, not *resolved*: the patron never answered, and recording that they did
    would be a false record. The letters stay put and stay readable.
    """
    async with await _client() as c:
        h, ws = await _register(c, "frozen7@example.com")
        pid, tid = await _live_project_with_a_task(c, ws, h)
        me = (await c.get("/auth/me", headers=h)).json()

        letters = []
        for kind, title in (
            (InboxItemKind.ESCALATION, "Đầu việc đứng khựng"),
            (InboxItemKind.OUTPUT_ACCEPTANCE, "Thành phẩm chờ ký"),
            (InboxItemKind.QUESTION, "Trưởng dự án hỏi"),
        ):
            letters.append(
                await app.state.container.inbox.place(
                    workspace_id=UUID(ws),
                    recipient_user_id=str(me["id"]),
                    kind=kind,
                    title=title,
                    project_id=UUID(pid),
                    task_id=UUID(tid),
                )
            )

        waiting = await c.get("/v1/inbox", headers=h)
        assert len({i["id"] for i in waiting.json()}) == len(letters)

        r = await c.post(
            f"/v1/projects/{pid}/phase", headers=h, json={"target_phase": "closed"}
        )
        assert r.status_code == 200, r.text

        # Nothing left in the waiting list…
        waiting = await c.get("/v1/inbox", headers=h)
        assert [i for i in waiting.json() if i["project_id"] == pid] == []

        # …but every letter is still there, marked void rather than answered.
        everything = {i["id"]: i for i in (await c.get("/v1/inbox?status=all", headers=h)).json()}
        for letter in letters:
            assert str(letter.id) in everything, f"thư {letter.title} biến mất"
            assert everything[str(letter.id)]["status"] == "void"


async def test_a_retired_letter_cannot_be_turned_into_an_answered_one() -> None:
    """Pressing a voided letter does nothing at all — including turning it into a resolved
    one. The patron never answered, and a stray press must not be recorded as their
    answer."""
    async with await _client() as c:
        h, ws = await _register(c, "frozen8@example.com")
        pid, tid = await _live_project_with_a_task(c, ws, h)
        me = (await c.get("/auth/me", headers=h)).json()
        letter = await app.state.container.inbox.place(
            workspace_id=UUID(ws),
            recipient_user_id=str(me["id"]),
            kind=InboxItemKind.ESCALATION,
            title="Đầu việc đứng khựng",
            project_id=UUID(pid),
            task_id=UUID(tid),
        )
        await c.post(
            f"/v1/projects/{pid}/phase", headers=h, json={"target_phase": "closed"}
        )

        r = await c.post(f"/v1/inbox/{letter.id}/resolve", headers=h)
        assert r.status_code == 200, r.text
        assert r.json()["status"] == "void"


async def test_a_letter_about_a_live_project_still_answers() -> None:
    """Bài đối chứng: chốt mới không được làm chết hộp thư của dự án đang chạy."""
    async with await _client() as c:
        h, ws = await _register(c, "frozen6@example.com")
        pid, tid = await _live_project_with_a_task(c, ws, h)

        me = (await c.get("/auth/me", headers=h)).json()
        letter = await app.state.container.inbox.place(
            workspace_id=UUID(ws),
            recipient_user_id=str(me["id"]),
            kind=InboxItemKind.ESCALATION,
            title="Đầu việc đứng khựng",
            project_id=UUID(pid),
            task_id=UUID(tid),
        )

        r = await c.post(f"/v1/inbox/{letter.id}/resolve", headers=h)
        assert r.status_code == 200, r.text


async def test_a_closed_project_is_still_fully_readable() -> None:
    """Đóng băng chứ không phải xoá sổ — FR-005 giữ lịch sử để người chủ xem lại."""
    async with await _client() as c:
        h, ws = await _register(c, "frozen2@example.com")
        pid, tid = await _live_project_with_a_task(c, ws, h)
        await force_phase(app.state.container.uow_factory, pid, ProjectStatus.CLOSED)

        for label, path in {
            "xem dự án": f"/v1/projects/{pid}",
            "xem bảng": f"/v1/projects/{pid}/tasks",
            "xem đầu việc": f"/v1/tasks/{tid}",
            "xem nhật ký": f"/v1/tasks/{tid}/log",
            "xem bình luận": f"/v1/tasks/{tid}/comments",
        }.items():
            r = await c.get(path, headers=h)
            assert r.status_code == 200, f"{label} không đọc được: {r.status_code}"


async def test_a_closed_project_can_still_be_thrown_away() -> None:
    """Lối duy nhất còn mở. Đóng băng nội dung mà không cho vứt cả dự án thì người chủ
    mắc kẹt vĩnh viễn với thứ họ đã tuyên bố là xong."""
    async with await _client() as c:
        h, ws = await _register(c, "frozen3@example.com")
        pid, _ = await _live_project_with_a_task(c, ws, h)
        await force_phase(app.state.container.uow_factory, pid, ProjectStatus.CLOSED)

        r = await c.delete(f"/v1/projects/{pid}", headers=h)
        assert r.status_code in (200, 204), r.text


async def test_a_live_project_is_untouched_by_the_freeze() -> None:
    """Bài đối chứng: chỗ chặn không được chặn nhầm dự án đang chạy."""
    async with await _client() as c:
        h, ws = await _register(c, "frozen4@example.com")
        pid, tid = await _live_project_with_a_task(c, ws, h)

        r = await c.post(f"/v1/tasks/{tid}/comments", headers=h, json={"body": "một lời"})
        assert r.status_code in (200, 201), r.text


# ── và khi vứt đi thì phải vứt sạch ───────────────────────────────────────────────


async def test_throwing_a_project_away_leaves_nothing_behind() -> None:
    """Xoá dự án phải xoá hết những gì nó sở hữu.

    Vòng xoá viết từ hồi một dự án chỉ có đầu việc, bình luận, thành phẩm, vai và ghế.
    Mọi bảng thêm sau đó — lượt chạy, lệnh gọi dậy, phiên làm việc, nhật ký đầu việc, bộ
    tiêu chí, chữ ký, thang phục hồi, kế hoạch, Bối cảnh, bản ghi nhịp rà, cuộc trò chuyện
    với Trưởng dự án — chưa bao giờ được thêm vào. Trên Postgres thì khoá ngoại chặn thẳng
    nên xoá bất kỳ dự án nào từng chạy agent là lỗi máy chủ; trên SQLite thì nó im lặng bỏ
    lại rác, nên bài kiểm đếm rác mới là bài bắt được cả hai.
    """
    async with await _client() as c:
        h, ws = await _register(c, "purge1@example.com")
        pid, tid = await _live_project_with_a_task(c, ws, h)
        await c.post(f"/v1/tasks/{tid}/comments", headers=h, json={"body": "một lời"})
        await c.put(f"/v1/tasks/{tid}/criteria", headers=h, json={"items": ["xong"]})
        await c.post(f"/v1/tasks/{tid}/status", headers=h, json={"status": "todo"})

        uowf = app.state.container.uow_factory
        async with uowf() as uow:
            assert await uow.task_logs.list_by_task(UUID(tid))  # có vết để mà bỏ lại

        r = await c.delete(f"/v1/projects/{pid}", headers=h)
        assert r.status_code in (200, 204), r.text

        async with uowf() as uow:
            assert await uow.tasks.get(UUID(tid)) is None
            assert await uow.task_logs.list_by_task(UUID(tid)) == []
            assert await uow.criteria.list_by_task(UUID(tid)) == []
            assert await uow.comments.list_by_task(UUID(tid)) == []
            assert await uow.runs.list_by_task(UUID(tid)) == []
            assert await uow.projects.get(UUID(pid)) is None


async def test_deleting_a_workspace_takes_its_projects_with_it() -> None:
    """Cùng một vòng xoá, cùng một lỗ — nên kiểm cả lối kia."""
    async with await _client() as c:
        h, ws = await _register(c, "purge2@example.com")
        pid, tid = await _live_project_with_a_task(c, ws, h)
        await c.post(f"/v1/tasks/{tid}/comments", headers=h, json={"body": "một lời"})
        # Không xoá được không gian làm việc cuối cùng, nên dựng thêm một cái để xoá
        # cái kia — bài này nói về vòng xoá, không nói về luật ấy.
        await c.post("/v1/workspaces", headers=h, json={"name": "Chỗ khác"})

        r = await c.delete(f"/v1/workspaces/{ws}", headers=h)
        assert r.status_code in (200, 204), r.text

        uowf = app.state.container.uow_factory
        async with uowf() as uow:
            assert await uow.projects.get(UUID(pid)) is None
            assert await uow.tasks.get(UUID(tid)) is None
            assert await uow.task_logs.list_by_task(UUID(tid)) == []
            assert await uow.comments.list_by_task(UUID(tid)) == []
