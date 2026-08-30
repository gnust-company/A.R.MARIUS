"""Tách toàn văn ra khỏi dòng sự kiện khi nó quá lớn (T099, FR-049).

Phép đọc quyết định chuyện này là phép đọc mở một lượt chạy ra: màn hình xin **mọi** sự kiện của
nó. Một nghìn sự kiện mà mỗi cái vác theo một megabyte prompt là truy vấn không ai phục vụ nổi,
và màn hình sẽ kéo cả đống ấy về chỉ để vẽ một danh sách tóm tắt một dòng (SC-014). Nên dòng sự
kiện giữ **phần đầu**, còn toàn văn nằm ở `run_event_blobs` và chỉ đi ra khi có người mở đúng cái
sự kiện ấy.

**Chỉ vài loại được phép có toàn văn ở đây, và danh sách ấy là một luật chứ không phải một tuỳ
chọn.** Thông điệp gửi agent, tham số gọi công cụ, và chữ agent sinh ra — ba thứ này vốn đã được
phép rời khỏi máy người dùng. Kết quả công cụ thì không, và không phải vì nó lớn: toàn văn thứ một
công cụ trả về không rời khỏi máy đã chạy nó, chấm hết (FR-043a). Ở đây không có ngưỡng nào cho nó
cả, vì không có gì để lưu.

**`omission_reason` để trống là cố ý.** Ba trạng thái trông giống nhau nếu gộp lại làm một, và hai
trong ba lần người đọc sẽ rút ra kết luận sai (FR-047):

- `truncated_by_policy` — máy đã cắt, phần còn lại **nằm nguyên trên máy người dùng**, mất hẳn.
- `not_exposed_by_cli` — CLI không bao giờ lộ ra, chưa từng có ở đây.
- cắt ở đây — phần còn lại **có ở ngay đây**, xin một câu là ra.

Cái thứ ba không phải một sự thiếu, nên nó không mang lý do thiếu. Nó chỉ nói *đây là phần đầu, và
cả phần còn lại đang chờ*: hai cột `truncated` với `original_byte_size`, cộng với việc có một hàng
trong `run_event_blobs`.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from uuid import UUID, uuid4

from armarius.infrastructure.daemon.models import RunEventBlobModel

# Loại sự kiện nào được mang toàn văn lên đây, và toàn văn ấy nằm dưới khoá nào (FR-049).
#
# Ánh xạ chứ không phải một tập tên: mỗi loại có đúng một trường dài, và nói thẳng ra trường nào
# là cách người đọc nhật ký không phải đoán khoá theo từng loại sự kiện.
FULL_TEXT_FIELDS: dict[str, str] = {
    "run.prompt": "prompt",
    "tool.started": "args",
    "assistant.message": "text",
    "assistant.thinking": "text",
}

# Không cắt một chuỗi ngắn hơn thế này dù có bao nhiêu chuỗi trong cùng một payload. Dưới mức
# này thì phần cắt ra không còn đọc được, và một trường không đọc được thì cắt hay bỏ là một.
MIN_LEAF_BYTES = 32


@dataclass(frozen=True)
class Split:
    """Một sự kiện sau khi đã tách: phần nằm lại trong dòng, và phần đi ra kho."""

    payload: dict
    #: Toàn văn, khi nó không vừa. None nghĩa là sự kiện vốn đã đủ nhỏ và không có gì tách cả.
    whole: str | None
    #: Khoá mà `whole` là toàn văn của nó.
    field: str
    byte_size: int

    @property
    def was_cut(self) -> bool:
        return self.whole is not None


def _cut(text: str, budget: int) -> str:
    """Cắt theo **bytes** nhưng không cắt giữa một ký tự.

    Ngưỡng là ngưỡng của thứ đi qua dây, mà dây đếm bytes. Người đọc thì đọc ký tự — nên chỗ cắt
    lùi về ranh giới ký tự gần nhất, chứ không trả ra một chuỗi hỏng ở đuôi.
    """
    raw = text.encode("utf-8")
    if len(raw) <= budget:
        return text
    return raw[:budget].decode("utf-8", errors="ignore")


def _string_leaves(value: object) -> int:
    if isinstance(value, str):
        return 1
    if isinstance(value, dict):
        return sum(_string_leaves(v) for v in value.values())
    if isinstance(value, (list, tuple)):
        return sum(_string_leaves(v) for v in value)
    return 0


def _shorten(value: object, budget: int) -> object:
    """Cắt mọi chuỗi trong một cấu trúc, giữ nguyên hình dạng của nó.

    Giữ hình dạng là điểm chính. Tham số gọi công cụ là một object, và cái làm nó lớn hầu như
    luôn là **một** giá trị — nội dung một tệp, một bản vá. Cắt riêng giá trị ấy thì màn hình vẫn
    đọc được *công cụ nào, tệp nào*, tức là gần hết thứ người ta cần từ một dòng danh sách. Đổi nó
    thành một chuỗi cắt ngang JSON thì mất sạch.

    Không chèn dấu gì vào chỗ cắt: một dấu ba chấm nằm trong giá trị là thứ sẽ theo chân người
    copy giá trị ấy đi chỗ khác. Việc *đã bị cắt* nói ở cấp sự kiện, không nói ở trong lòng nó.
    """
    if isinstance(value, str):
        return _cut(value, budget)
    if isinstance(value, dict):
        return {k: _shorten(v, budget) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_shorten(v, budget) for v in value]
    return value


def split(event_type: str, payload: dict, limit: int) -> Split:
    """Chia một sự kiện thành phần nằm lại và phần đi ra kho.

    Trả về chính payload đã cho khi không có gì phải tách — loại sự kiện không được phép, khoá
    không có, hoặc nó vốn đã vừa. Không sao chép vô cớ: đường này chạy cho **mọi** sự kiện của mọi
    lượt chạy, và tuyệt đại đa số không có gì để làm.
    """
    field = FULL_TEXT_FIELDS.get(event_type)
    if field is None or field not in payload:
        return Split(payload=payload, whole=None, field="", byte_size=0)

    value = payload[field]
    whole = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, default=str)
    size = len(whole.encode("utf-8"))
    if size <= limit:
        return Split(payload=payload, whole=None, field=field, byte_size=size)

    if isinstance(value, str):
        opening: object = _cut(value, limit)
    else:
        # Chia ngưỡng cho số chuỗi có trong đó, để một object nhiều trường không nở ra quá
        # ngưỡng chỉ vì trường nào cũng được cắt tới đúng ngưỡng ấy.
        share = max(MIN_LEAF_BYTES, limit // max(1, _string_leaves(value)))
        opening = _shorten(value, share)

    return Split(
        payload={**payload, field: opening},
        whole=whole,
        field=field,
        byte_size=size,
    )


def keeping(
    *, run_event_id: UUID, workspace_id: UUID, split: Split
) -> RunEventBlobModel:
    """Hàng giữ toàn văn cho một sự kiện vừa bị cắt.

    Mang theo `workspace_id` của riêng nó dù suy ra được qua lượt chạy: đọc nhật ký là đường
    nóng, và nối runs → projects → workspaces mỗi lần đọc chỉ để biết nó thuộc về ai là một cái
    giá không đổi lại được gì. Rào theo workspace là bắt buộc (FR-051, Hiến pháp — Điều I), nên
    thứ để rào phải nằm ngay chỗ đọc.
    """
    return RunEventBlobModel(
        id=uuid4(),
        run_event_id=run_event_id,
        workspace_id=workspace_id,
        field=split.field,
        content=split.whole or "",
        byte_size=split.byte_size,
    )
