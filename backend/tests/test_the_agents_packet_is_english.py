"""Chữ máy chủ tự soạn rồi đọc lại vào gói tin gửi agent thì phải là tiếng Anh (Hiến pháp VII).

`wake_reason.ENGLISH` đã khoá được **lý do đánh thức**: nó là bảng mã, và `WakeEngine.enqueue`
nhận kiểu `WakeReason` chứ không nhận chuỗi, nên một câu tiếng Việt không lọt vào mục "Why you
were woken" được. Nhưng gói tin còn hai ô nữa mang chữ tự do, và **không ô nào có kiểu bảo vệ**:

  * `## Your recorded next action` đọc thẳng `task.next_action`;
  * `## New messages since you last worked` đọc thẳng thân các `Comment`.

Cả hai ô ấy phần lớn thời gian mang chữ *do agent tự viết* — thứ không ai được sửa. Nhưng có
những lối máy chủ tự soạn rồi ghi vào đó, và đấy mới là chỗ điều luật chạm tới: câu ấy là chữ
hệ thống, và nó sẽ được đọc lại cho một agent nghe.

Bài này quét **chuỗi có sẵn trong mã nguồn** chảy vào hai ô đó. Nó không đụng tới giá trị lúc
chạy: tiêu đề đầu việc, phần mô tả, ghi chú thợ tự gõ đều là chữ của người và của agent, không
phải chữ của hệ thống.

Vì sao là phép quét chứ không phải ba bài kiểm ba chỗ: ba chỗ tìm được hôm nay đều nằm cạnh
những dòng mà tác giả *đã* cân nhắc đúng điều luật này rồi bỏ sót hàng xóm. Một danh sách chép
tay lại hụt đúng kiểu ấy lần nữa. Bảng dưới đây bắt cả chỗ thứ tư chưa ai viết.
"""

from __future__ import annotations

import ast
import pathlib

VIETNAMESE = "ăâđêôơưàáảãạèéẻẽẹìíỉĩịòóỏõọùúủũụỳýỷỹỵ"
_BACKEND = pathlib.Path(__file__).resolve().parents[1] / "armarius"

#: Ô nào trong gói tin mang chữ tự do. Tên ô, chứ không phải tên tệp: thêm một lối ghi mới ở
#: bất cứ đâu trong `armarius/` cũng bị quét, kể cả tệp chưa tồn tại lúc viết bài này.
_FIELDS_READ_BACK_TO_THE_AGENT = ("next_action", "body")

#: `Comment.body` là ô duy nhất tên `body` được đọc lại vào gói tin. Các `body=` khác — thân
#: mục hộp thư — chỉ lên màn người chủ, nên tiếng Việt ở đó là đúng chỗ, không phải lỗi.
_COMMENT_CALLS = ("Comment",)


def _has_vietnamese(text: str) -> bool:
    lowered = text.lower()
    return any(ch in lowered for ch in VIETNAMESE)


def _literal_text(node: ast.AST) -> str | None:
    """Chữ có sẵn trong mã của một nút, gồm cả f-string ghép nhiều mảnh.

    Trả `None` cho thứ chỉ biết lúc chạy — một biến, một lời gọi hàm — vì bài này chỉ nói về
    câu do mã nguồn viết sẵn.
    """
    if isinstance(node, ast.Constant):
        return node.value if isinstance(node.value, str) else None
    if isinstance(node, ast.JoinedStr):
        parts = [
            v.value
            for v in node.values
            if isinstance(v, ast.Constant) and isinstance(v.value, str)
        ]
        return "".join(parts)
    if isinstance(node, ast.BoolOp):
        # `note or "..."` — lối viết giá trị mặc định. Vế nào là chữ có sẵn thì vế ấy là
        # câu của máy chủ; vế biến là chữ của người gọi và không thuộc phạm vi bài này.
        parts = [t for t in (_literal_text(v) for v in node.values) if t]
        return "\n".join(parts) if parts else None
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        left, right = _literal_text(node.left), _literal_text(node.right)
        return (left or "") + (right or "") if (left or right) else None
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
        # `f"...".strip()` và họ hàng: chữ nằm ở người nhận lời gọi.
        return _literal_text(node.func.value)
    return None


def _sources() -> list[tuple[pathlib.Path, ast.Module]]:
    out = []
    for path in sorted(_BACKEND.rglob("*.py")):
        if "alembic" in path.parts:
            continue
        out.append((path, ast.parse(path.read_text(encoding="utf-8"))))
    return out


def _server_written_lines() -> list[tuple[str, int, str]]:
    """Mọi câu có sẵn trong mã được ghi vào một ô mà agent sẽ đọc lại."""
    found: list[tuple[str, int, str]] = []
    for path, tree in _sources():
        rel = str(path.relative_to(_BACKEND))
        for node in ast.walk(tree):
            # `task.next_action = "..."` và `next_action = "..."`
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    name = (
                        target.attr
                        if isinstance(target, ast.Attribute)
                        else target.id
                        if isinstance(target, ast.Name)
                        else None
                    )
                    if name == "next_action":
                        text = _literal_text(node.value)
                        if text:
                            found.append((rel, node.lineno, text))
            # `Comment(..., body="...")` và `next_action=` truyền vào bất cứ lời gọi nào
            if isinstance(node, ast.Call):
                func = node.func
                called = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
                for kw in node.keywords:
                    if kw.arg not in _FIELDS_READ_BACK_TO_THE_AGENT:
                        continue
                    if kw.arg == "body" and called not in _COMMENT_CALLS:
                        continue
                    text = _literal_text(kw.value)
                    if text:
                        found.append((rel, kw.value.lineno, text))
    return found


def test_the_packet_has_at_least_one_line_to_check() -> None:
    """Phép quét đọc ra rỗng thì mọi bài dưới đây xanh vì lý do sai."""
    assert len(_server_written_lines()) >= 5


def test_no_server_written_line_the_agent_reads_back_is_vietnamese() -> None:
    offenders = [
        f"{rel}:{line} → {text[:60]}"
        for rel, line, text in _server_written_lines()
        if _has_vietnamese(text)
    ]
    assert not offenders, (
        "Những câu này do máy chủ soạn rồi được đọc lại vào gói tin gửi agent, "
        "nên phải là tiếng Anh (Hiến pháp VII):\n  " + "\n  ".join(offenders)
    )


def test_the_wake_cause_table_stays_english() -> None:
    """Bảng lý do đánh thức là bản của agent, nên không câu nào trong đó có tiếng Việt."""
    from armarius.domain.services.wake_reason import ENGLISH

    offenders = [code for code, phrase in ENGLISH.items() if _has_vietnamese(phrase)]
    assert not offenders, offenders


def test_the_wake_packet_scaffolding_stays_english() -> None:
    """Chữ khung của chính gói tin — tiêu đề mục, câu dẫn — cũng là bản của agent."""
    path = _BACKEND / "domain" / "services" / "wake_prompt.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    docs = {
        id(n.body[0].value)
        for n in ast.walk(tree)
        if isinstance(n, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
        and n.body
        and isinstance(n.body[0], ast.Expr)
        and ast.get_docstring(n) is not None
    }
    offenders = [
        f"{n.lineno} → {n.value[:60]}"
        for n in ast.walk(tree)
        if isinstance(n, ast.Constant)
        and isinstance(n.value, str)
        and id(n) not in docs
        and _has_vietnamese(n.value)
    ]
    assert not offenders, offenders
