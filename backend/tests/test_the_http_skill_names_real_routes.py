"""Kỹ năng HTTP dạy agent gọi cửa nào thì cửa ấy phải có thật, và cửa nào có thật thì phải được dạy.

`armarius-http/SKILL.md` là tờ hướng dẫn duy nhất một agent chạy bằng curl đọc để biết gọi
gì. Nó là **tài liệu**, nên không có gì bắt nó đi cùng mã: gỡ một route đi thì kỹ năng vẫn
nằm im, vẫn dạy y như cũ, và agent nào làm theo cũng ăn 404 — đúng chuyện đã xảy ra với
`/tasks/{id}/claim`, cửa bị gỡ ở FR-072 mà tờ hướng dẫn vẫn bảo "claim trước khi làm".

Bài này nối hai đầu lại bằng bảng route thật của app, quét **cả hai chiều**:

  * mọi lời gọi trong SKILL.md phải trỏ tới một route đang tồn tại — bắt lúc gỡ/đổi tên cửa;
  * mọi route `/agent/*` phải được SKILL.md nhắc tới — bắt lúc thêm cửa mà quên dạy.

Chiều thứ hai mới là chiều đáng giá. Lần hỏng vừa rồi không phải chỉ một dòng sai: tờ hướng
dẫn kể 6 cửa trên 25 cửa có thật, thiếu sạch phần của Trưởng dự án, nên một Trưởng dự án chạy
bằng kỹ năng này **không ký nổi** — mà `done` thì đòi đủ hai chữ ký. Một danh sách chép tay chỉ
canh được những cửa người viết đang nhìn; bảng route thì kể cả cửa viết sau bài này.
"""

from __future__ import annotations

import pathlib
import re

from armarius.main import create_app

_SKILL = (
    pathlib.Path(__file__).resolve().parents[1]
    / "static"
    / "skills"
    / "armarius-http"
    / "SKILL.md"
)

#: Hai cửa onboarding do runtime của Trợ lý workspace lái, không phải do agent cầm curl gọi:
#: chúng thuộc một phiên phỏng vấn có sẵn `session_id`, thứ không bao giờ tới tay thợ. Miễn
#: có tên ở đây để bài quét vẫn chặt với mọi cửa còn lại.
_NOT_FOR_THE_CURL_AGENT = {
    ("POST", "/agent/onboarding/{session_id}/question"),
    ("POST", "/agent/onboarding/{session_id}/complete"),
}

#: `curl ... -X POST "API_BASE_URL/agent/..."` — phương thức và URL luôn nằm cùng một dòng.
_CALL = re.compile(r'curl[^\n"]*?(?:-X\s+(?P<method>[A-Z]+)\s+)?"API_BASE_URL(?P<path>/\S*?)"')


def _documented() -> set[tuple[str, str]]:
    """Các lời gọi SKILL.md dạy, đã đổi chỗ giữ chỗ VIẾT_HOA thành `{tham_số}` của route."""
    out: set[tuple[str, str]] = set()
    for m in _CALL.finditer(_SKILL.read_text(encoding="utf-8")):
        segments = [
            f"{{{seg.lower()}}}" if re.fullmatch(r"[A-Z][A-Z_]*", seg) else seg
            for seg in m.group("path").split("/")
        ]
        out.add((m.group("method") or "GET", "/".join(segments)))
    return out


def _real() -> set[tuple[str, str]]:
    """Bảng route thật của app, chỉ phần `/agent/*`."""
    out: set[tuple[str, str]] = set()
    for route in create_app().routes:
        path = getattr(route, "path", "")
        methods = getattr(route, "methods", None)
        if not methods or not path.startswith("/agent"):
            continue
        for method in methods:
            if method not in ("HEAD", "OPTIONS"):
                out.add((method, path))
    return out


def test_moi_loi_goi_trong_ky_nang_deu_tro_toi_mot_route_co_that() -> None:
    documented, real = _documented(), _real()
    assert documented, (
        "không đọc được lời gọi nào trong SKILL.md — hỏng phép quét, không phải hết lỗi"
    )
    dead = sorted(documented - real)
    assert not dead, (
        "SKILL.md dạy agent gọi những cửa không tồn tại (agent sẽ ăn 404): "
        + ", ".join(f"{m} {p}" for m, p in dead)
    )


def test_moi_route_agent_deu_duoc_ky_nang_day() -> None:
    undocumented = sorted(_real() - _documented() - _NOT_FOR_THE_CURL_AGENT)
    assert not undocumented, (
        "có cửa `/agent/*` mà SKILL.md không nhắc — agent chạy bằng curl không biết đường dùng: "
        + ", ".join(f"{m} {p}" for m, p in undocumented)
    )
