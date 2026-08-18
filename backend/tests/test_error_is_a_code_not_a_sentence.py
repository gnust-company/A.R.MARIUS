"""Lời từ chối của máy chủ là **mã cớ kèm tham số**, không phải câu đã dựng (T184, FR-084a).

Cùng một lời từ chối có hai người đọc không đọc chung một thứ tiếng. Agent gọi mặt giao
tiếp không có ngôn ngữ giao diện để chọn, nên bản của nó là tiếng Anh (Hiến pháp VII).
Người chủ đọc đúng lời ấy trên màn, bằng thứ tiếng họ đã chọn. Một câu dựng sẵn ở máy chủ
chỉ phục vụ được một trong hai.

Bốn thứ được canh ở đây:

  * mọi lối từ chối trả về `code` (và `params` khi câu cần chỗ điền), chứ không chỉ `detail`;
  * `detail` — bản duy nhất agent đọc — không còn một chữ tiếng Việt nào;
  * bảng câu chữ hai bên **khớp mã**: máy chủ có mã nào thì giao diện phải có câu cho mã ấy,
    và ngược lại, vì lệch một chiều nào cũng cho ra một màn hình trắng chữ;
  * lời từ chối khép vòng phụ thuộc **nêu đích danh vòng đi qua đâu** (T190, FR-032).
"""

from __future__ import annotations

import ast
import pathlib
import re

from httpx import AsyncClient

from armarius.shared.errors import ENGLISH, CodedError, NotFound, render_en
from tests.support.planning import OperatingProject, client, operating_project

VIETNAMESE = "ăâđêôơưàáảãạèéẻẽẹìíỉĩịòóỏõọùúủũụỳýỷỹỵ"
_I18N = pathlib.Path(__file__).resolve().parents[2] / "frontend" / "src" / "i18n"
_BACKEND = pathlib.Path(__file__).resolve().parents[1] / "armarius"

# Ba chỗ ném lỗi với mã **tính lúc chạy**, nên phép quét mã nguồn không đọc ra được. Ghi
# tên từng chỗ chứ không bỏ qua cả loại: một mã dựng lúc chạy là một mã không ai tra ngược
# được, nên thêm chỗ thứ tư phải là một quyết định có lý do, không phải chuyện lọt qua.
_CODE_FORWARDED_AT_RUNTIME = {
    # Người gọi truyền mã vào; bốn chỗ gọi đều truyền chuỗi có sẵn trong bảng.
    ("presentation/api/events.py", "NotFound"),
    # Chuyển tiếp mã của một lời từ chối khác, đổi mã trạng thái chứ không đổi lý do.
    ("presentation/api/workspaces.py", "NotFound"),
    # Một hằng số ngay đầu tệp, để cùng một lời từ chối không bị chép lại ở mỗi cửa.
    ("presentation/api/frozen.py", "ProjectClosed"),
}

# Lời từ chối mà **máy khách tự dựng**, không máy chủ nào gửi: lượt làm mới phiên hỏng thì
# không có phản hồi nào để đọc mã ra. Ghi tên ở đây chứ không nới lỏng phép so khớp, để một
# mã mồ côi thật vẫn bị bắt.
_CLIENT_ONLY = {"session_expired"}


def _has_vietnamese(text: str) -> bool:
    lowered = text.lower()
    return any(ch in lowered for ch in VIETNAMESE)


def _interface_codes(language: str) -> set[str]:
    """The codes the screen has a phrase for, read straight out of the phrase table."""
    source = (_I18N / f"{language}.ts").read_text(encoding="utf-8")
    block = re.search(r"\n  errors: \{\n(.*?)\n  \},\n", source, re.S)
    assert block, f"{language}.ts has no errors block"
    return set(re.findall(r"^    ([a-z0-9_]+):", block.group(1), re.M))


# ── the wire's half ───────────────────────────────────────────────────────────


def test_the_agents_copy_of_a_refusal_has_no_vietnamese_in_it() -> None:
    """Hiến pháp VII: chữ hệ thống gửi agent phải tiếng Anh. `detail` là bản của agent."""
    guilty = [code for code, text in ENGLISH.items() if _has_vietnamese(text)]
    assert not guilty, guilty


def test_a_refusal_carries_its_parts_instead_of_a_finished_sentence() -> None:
    refusal = NotFound("role_not_in_roster", role="backend")
    assert refusal.code == "role_not_in_roster"
    assert refusal.params == {"role": "backend"}
    # Vẫn là một `LookupError`, vì vài chỗ bắt đúng loại đó để hiểu là "không còn nữa".
    assert isinstance(refusal, LookupError)
    assert "backend" in str(refusal)
    assert refusal.to_payload() == {
        "detail": "Role 'backend' is not in this project's roster.",
        "code": "role_not_in_roster",
        "params": {"role": "backend"},
    }


def test_a_code_nobody_has_worded_yet_still_says_which_rule_refused() -> None:
    """Rơi về chính cái mã, không rơi về rỗng: đọc hơi lạ vẫn hơn không đọc được gì."""
    assert render_en("a_rule_written_after_this_build", {}) == "a_rule_written_after_this_build"
    # Thiếu một chỗ điền thì cũng không được ném ra giữa lúc đang trả lời.
    assert "(unknown)" in render_en("role_not_in_roster", {})


# ── every `raise` in the source, not just every row in the table ──────────────


def _coded_error_names() -> set[str]:
    """Every class in the codebase that ends up a `CodedError`, by bare name.

    Resolved by walking the class statements rather than importing: a name is enough to
    match a `raise`, and importing every module to ask `issubclass` drags the whole
    application up for a text check.
    """
    names = {"CodedError", "NotFound", "BadRequest", "Forbidden", "Unauthorized", "Conflict"}
    statements = []
    for path in _BACKEND.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                bases = {b.id for b in node.bases if isinstance(b, ast.Name)}
                statements.append((node.name, bases))
    # Repeat until nothing new joins: a subclass may be read before its base.
    changed = True
    while changed:
        changed = False
        for name, bases in statements:
            if name not in names and bases & names:
                names.add(name)
                changed = True
    return names


def _raised_codes() -> list[tuple[str, int, str, str | None]]:
    """(file, line, first argument) for every `raise <a coded error>(...)` in the source.

    A first argument that is not a plain string literal reads as ``None`` — that is a
    refusal whose code cannot be checked here, and the test treats it as a failure for the
    same reason: a code assembled at run time is a code nobody can look up.
    """
    coded = _coded_error_names()
    found: list[tuple[str, int, str, str | None]] = []
    for path in sorted(_BACKEND.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Raise) or not isinstance(node.exc, ast.Call):
                continue
            called = node.exc.func
            # Both `raise Thing(...)` and `raise module.Thing(...)`. The second form is
            # what the sweep that built this table missed — its pattern only knew the
            # first, so three refusals kept a whole sentence where the code goes.
            name = (called.id if isinstance(called, ast.Name)
                    else called.attr if isinstance(called, ast.Attribute) else None)
            if name not in coded or not node.exc.args:
                continue
            first = node.exc.args[0]
            literal = first.value if isinstance(first, ast.Constant) and isinstance(
                first.value, str) else None
            found.append((str(path.relative_to(_BACKEND)), node.lineno, name, literal))
    return found


def test_every_refusal_in_the_source_uses_a_code_the_table_knows() -> None:
    """Mắt xích ở giữa mà hai bài kiểm bảng không canh.

    Chúng canh "mã trong bảng thì sạch" và "hai bảng khớp nhau". Một chỗ ném lỗi truyền
    thẳng cả câu vào ô của mã thì **không mã nào vào bảng cả**, nên cả hai đều không có
    gì để soi: câu đó thành `code` trong phản hồi, và thành luôn `detail` vì tra bảng
    không thấy thì rơi về chính nó.
    """
    raised = _raised_codes()
    assert len(raised) > 100, f"phép quét hỏng, chỉ thấy {len(raised)} chỗ ném lỗi"
    strays = [
        (f, line, cls, arg)
        for f, line, cls, arg in raised
        if arg not in ENGLISH and (f, cls) not in _CODE_FORWARDED_AT_RUNTIME
    ]
    assert not strays, "chỗ ném lỗi dùng mã không có trong bảng:\n" + "\n".join(
        f"  {f}:{line} → {arg!r}" for f, line, cls, arg in strays
    )


#: Lỗi dựng sẵn của Python mà `install_error_handlers` bắt và **đổi thành một phản hồi từ
#: chối**: `ValueError` → 400, `LookupError` (và `KeyError` là con nó) → 404,
#: `PermissionError` → 403. Ném trần một trong số này là gửi đi một lời từ chối không mã.
#: `RuntimeError` không có ở đây vì nó rơi ra 500 — đấy là lỗi lập trình, không phải lời
#: từ chối, và một cái 500 thì không ai dựng câu cho người đọc cả.
_REFUSAL_BUILTINS = {"ValueError", "LookupError", "PermissionError", "KeyError"}

#: Những chỗ ném trần **không tới được tay người gọi**, kèm lý do từng chỗ. Ghi tên chứ
#: không nới phép quét: một chỗ thứ tư phải là quyết định có lý do, không phải chuyện lọt.
_NEVER_REACHES_A_CALLER = {
    # Bộ soát của pydantic. Pydantic bắt `ValueError` ngay trong lượt soát và tự dựng
    # phản hồi 422 của nó, nên câu này không đi qua bảng mã của ta.
    ("presentation/schemas.py", "ValueError"),
    # Đọc thẻ: người gọi bắt lại rồi ném ra lời từ chối có mã (`invalid_access_token`).
    ("infrastructure/security/jwt.py", "ValueError"),
    # Băm mật khẩu: chặn lập trình viên truyền chuỗi rỗng, không phải cửa nhận yêu cầu.
    ("infrastructure/security/password.py", "ValueError"),
    # Sổ bộ chuyển đổi: tra một loại chưa đăng ký là sai cấu hình lúc dựng, không phải
    # một yêu cầu hỏng.
    ("infrastructure/adapters/registry.py", "LookupError"),
}


def _bare_refusals() -> list[tuple[str, int, str]]:
    """Mọi `raise` một lỗi dựng sẵn mà tầng phản hồi sẽ biến thành lời từ chối."""
    coded = _coded_error_names()
    found: list[tuple[str, int, str]] = []
    for path in sorted(_BACKEND.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Raise):
                continue
            exc = node.exc
            called = exc.func if isinstance(exc, ast.Call) else exc
            name = (
                called.id
                if isinstance(called, ast.Name)
                else called.attr
                if isinstance(called, ast.Attribute)
                else None
            )
            # `NotFound` là `LookupError`, `BadRequest` là `ValueError` — họ mang mã sẵn.
            if name in coded or name not in _REFUSAL_BUILTINS:
                continue
            found.append((str(path.relative_to(_BACKEND)), node.lineno, name))
    return found


def test_no_refusal_leaves_the_server_without_a_code() -> None:
    """Lỗ mà bài kiểm trên **không** bịt được, và đã lọt bốn cửa suốt hai tháng.

    `_raised_codes` chỉ soi các lệnh ném thuộc họ mã lỗi. Một `raise ValueError(f"...")`
    trần thì không thuộc họ ấy, nên phép quét đi qua nó — trong khi tầng phản hồi vẫn
    ngoan ngoãn đổi nó thành `400 {"detail": "unknown status 'xong'"}`: không `code`,
    không `params`. Màn hình không dựng được câu tiếng Việt, còn agent nhận đúng câu ấy.

    Bốn cửa lọt (`inbox`, `tasks`, `agent` ×2) đều tìm ra bằng tay, mỗi lần một cửa. Bài
    này thay chỗ cho việc tìm bằng tay.
    """
    strays = [
        (f, line, name)
        for f, line, name in _bare_refusals()
        if (f, name) not in _NEVER_REACHES_A_CALLER
    ]
    assert not strays, (
        "lời từ chối ném trần, tới người gọi mà không có mã:\n"
        + "\n".join(f"  {f}:{line} → raise {name}(...)" for f, line, name in strays)
    )


# ── the screen's half ─────────────────────────────────────────────────────────


def test_every_code_the_server_can_send_has_a_phrase_on_screen() -> None:
    for language in ("en", "vi"):
        missing = sorted(set(ENGLISH) - _interface_codes(language))
        assert not missing, f"{language}.ts thiếu câu cho: {missing}"


def test_the_screen_has_no_phrase_for_a_code_the_server_never_sends() -> None:
    """Chiều ngược lại. Một câu mồ côi không hỏng gì hôm nay, nhưng nó là dấu của một mã
    vừa bị đổi tên ở một phía — và phía kia thì chưa."""
    for language in ("en", "vi"):
        orphans = sorted(_interface_codes(language) - set(ENGLISH) - _CLIENT_ONLY)
        assert not orphans, f"{language}.ts còn câu thừa cho: {orphans}"


def test_the_two_languages_carry_the_same_placeholders() -> None:
    """Chỗ điền lệch nhau là một câu tiếng Việt mất tham số mà bài kiểm nào cũng xanh."""
    for code, template in ENGLISH.items():
        wanted = set(re.findall(r"\{(\w+)\}", template))
        for language in ("en", "vi"):
            source = (_I18N / f"{language}.ts").read_text(encoding="utf-8")
            line = re.search(rf"^    {code}: '(.*)',$", source, re.M)
            assert line, f"{language}.ts thiếu dòng {code}"
            assert set(re.findall(r"\{\{(\w+)\}\}", line.group(1))) == wanted, code


# ── through the running server ────────────────────────────────────────────────


async def _a_task(c: AsyncClient, p: OperatingProject) -> str:
    r = await c.post(
        f"/agent/projects/{p.project_id}/tasks",
        headers=p.leader_headers,
        json={
            "title": "Kết xuất báo cáo tháng",
            "description": "Gom số liệu rồi kết xuất.",
            "assignee_marius_id": p.worker_id,
            "plan_item_id": p.item_id(),
        },
    )
    assert r.status_code == 201, r.text
    return str(r.json()["id"])


async def test_a_refusal_over_http_answers_with_a_code_and_no_vietnamese() -> None:
    async with client() as c:
        p = await operating_project(c, "coded-errors@armarius.dev")
        task_id = await _a_task(c, p)
        # Đóng thẳng một đầu việc vừa mở: bảng chuyển trạng thái từ chối.
        refused = await c.post(
            f"/agent/tasks/{task_id}/status",
            headers=p.worker_headers,
            json={"status": "done"},
        )
    assert refused.status_code == 409, refused.text
    body = refused.json()
    assert body["code"], body
    assert body["code"] in ENGLISH, body["code"]
    assert not _has_vietnamese(body["detail"]), body["detail"]
    # Tham số là *mảnh*, không phải một câu hệ thống khác đội lốt tham số.
    assert all(not _has_vietnamese(str(v)) for v in body["params"].values()), body["params"]


async def test_a_missing_thing_answers_404_with_the_code_that_says_which_thing() -> None:
    async with client() as c:
        p = await operating_project(c, "coded-404@armarius.dev")
        gone = await c.get(
            "/v1/tasks/00000000-0000-0000-0000-000000000000", headers=p.headers
        )
    assert gone.status_code == 404, gone.text
    assert gone.json()["code"] == "task_not_found", gone.text


# ── T190: the ring is named ───────────────────────────────────────────────────


async def test_a_refused_cycle_names_the_tasks_it_would_run_through() -> None:
    """FR-032. Từ chối suông thì người đọc phải tự dò trên một cái bảng mà chính cạnh vừa
    bị chặn là thứ duy nhất chưa có ở đó."""
    async with client() as c:
        p = await operating_project(c, "coded-cycle@armarius.dev")
        first, second, third = [await _a_task(c, p) for _ in range(3)]
        for waiter, blocker in ((first, second), (second, third)):
            edge = await c.post(
                f"/v1/tasks/{waiter}/dependencies",
                headers=p.headers,
                json={"blocks_task_id": blocker},
            )
            assert edge.status_code in (200, 201), edge.text
        closed = await c.post(
            f"/v1/tasks/{third}/dependencies",
            headers=p.headers,
            json={"blocks_task_id": first},
        )
        codes = {
            tid: (await c.get(f"/v1/tasks/{tid}", headers=p.headers)).json()["identifier"]
            for tid in (first, second, third)
        }
    assert closed.status_code == 422, closed.text
    body = closed.json()
    assert body["code"] == "dependency_cycle", body
    ring = body["params"]["cycle"]
    for identifier in codes.values():
        assert identifier in ring, ring
    # Khép lại chính nó, nên đọc ra là một vòng chứ không phải một đoạn.
    assert ring.split(" → ")[0] == ring.split(" → ")[-1] == codes[third]


def test_the_ring_is_carried_as_a_parameter_not_baked_into_the_wording() -> None:
    refusal = CodedError("dependency_cycle", cycle="A → B → A")
    assert refusal.params == {"cycle": "A → B → A"}
    assert str(refusal) == "This dependency would close a cycle: A → B → A."
