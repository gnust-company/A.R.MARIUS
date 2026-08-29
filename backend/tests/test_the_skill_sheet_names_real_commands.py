"""Tờ hướng dẫn dạy lệnh nào thì lệnh ấy phải có thật, và lệnh nào có thật thì phải được dạy (T140).

`static/skills/armarius-http/SKILL.md` là tờ duy nhất một agent đọc để biết nó gọi ngược bằng
cách nào. Nó là **tài liệu**, nên không có gì bắt nó đi cùng mã: đổi tên một lệnh thì tờ hướng
dẫn vẫn nằm im, vẫn dạy y như cũ, và agent nào làm theo cũng chạy vào một lệnh không tồn tại.

Bài này nối hai đầu lại bằng chính bảng lệnh trong mã Go, quét **cả hai chiều**:

  * mọi lệnh trong SKILL.md phải có trong bảng — bắt lúc gỡ hoặc đổi tên lệnh;
  * mọi lệnh trong bảng phải được SKILL.md nhắc — bắt lúc thêm lệnh mà quên dạy.

Chiều thứ hai mới là chiều đáng giá, và nó là chiều bản trước của bài này đã bắt được một lần:
tờ hướng dẫn kể 6 cửa trên 25 cửa có thật, thiếu sạch phần của Trưởng dự án, nên một Trưởng dự
án chạy bằng nó **không ký nổi** — mà `done` thì đòi đủ hai chữ ký.

**Vì sao đọc thẳng mã Go chứ không sinh ra một tệp danh sách.** Một tệp sinh ra là một bản chép
thứ ba phải nhớ chạy lại, và cái quên chạy lại đúng là cái bài này tồn tại để bắt. Bảng lệnh nằm
trong `registry.go` và hai tệp bên cạnh nó, ở một dạng cố định; quét không ra lệnh nào thì bài
này **đỏ**, chứ không xanh — hỏng phép quét không được đọc thành hết lỗi.
"""

from __future__ import annotations

import pathlib
import re

_ROOT = pathlib.Path(__file__).resolve().parents[2]
_SKILL = _ROOT / "backend" / "static" / "skills" / "armarius-http" / "SKILL.md"
_REGISTRY = _ROOT / "daemon" / "internal" / "callback"

#: `Name:    "task show",` theo ngay sau là `Group:` — cách bảng khai một lệnh, và chỗ duy nhất
#: khai nó. Đòi cả dòng `Group:` chứ không chỉ dòng `Name:`: một tham số cũng có tên, và bản
#: trước của phép quét đọc `Name: "limit"` của một tham số thành một lệnh tên `limit` — rồi bắt
#: SKILL.md phải dạy nó (bắt được 2026-08-29, lúc thêm `workdir changes`).
_DECLARED = re.compile(
    r'^\s*Name:\s*"([a-z][a-z0-9 -]*)",\s*\n\s*Group:', re.MULTILINE
)

#: `armarius task show ...` trong một khối lệnh của tờ hướng dẫn.
_TAUGHT = re.compile(
    r'^[ \t]*armarius[ \t]+([a-z][a-z0-9-]*(?:[ \t]+[a-z][a-z0-9-]*)?)', re.MULTILINE
)

#: Không phải lệnh: `armarius help` là lối vào, và `armarius <command> -h` là một chỗ giữ chỗ.
_NOT_A_COMMAND = {"help", "mcp"}


def _declared() -> set[str]:
    names: set[str] = set()
    for source in sorted(_REGISTRY.glob("*.go")):
        if source.name.endswith("_test.go"):
            continue
        names |= set(_DECLARED.findall(source.read_text(encoding="utf-8")))
    return names


def _taught() -> set[str]:
    sheet = _SKILL.read_text(encoding="utf-8")
    taught: set[str] = set()
    for phrase in _TAUGHT.findall(sheet):
        words = phrase.split()
        # Hai từ trước, rồi mới một từ: `task show` là một lệnh, `task` thì không.
        taught.add(" ".join(words[:2]) if len(words) > 1 else words[0])
    return {name for name in taught if name not in _NOT_A_COMMAND}


def test_phep_quet_con_doc_duoc_ca_hai_dau() -> None:
    """Hỏng phép quét phải đỏ ở đây, không được im lặng làm hai bài dưới xanh."""
    assert _declared(), (
        f"không đọc được lệnh nào trong {_REGISTRY} — hỏng phép quét, không phải hết lệnh"
    )
    assert _taught(), (
        f"không đọc được lệnh nào trong {_SKILL} — hỏng phép quét, không phải tờ hướng dẫn rỗng"
    )


def test_moi_lenh_trong_to_huong_dan_deu_co_that() -> None:
    invented = sorted(_taught() - _declared())
    assert not invented, (
        "SKILL.md dạy agent chạy những lệnh không tồn tại: " + ", ".join(invented)
    )


def test_moi_lenh_co_that_deu_duoc_day() -> None:
    untaught = sorted(_declared() - _taught())
    assert not untaught, (
        "có lệnh agent gọi được mà SKILL.md không nhắc — agent không biết đường dùng: "
        + ", ".join(untaught)
    )


def test_to_huong_dan_khong_con_day_token_song_lau_hay_curl() -> None:
    """Bản cũ dạy đúng thứ vừa bị gỡ: 22 lời gọi `curl`, 22 lần nhắc token sống lâu (FR-014g).

    Không phải chuyện gọn gàng. Một tờ hướng dẫn dạy agent tự viết lời gọi mạng kèm token là
    một tờ dạy agent làm cái việc mà từ T135 trở đi sẽ hỏng — và nó sẽ hỏng theo kiểu agent tự
    đi sửa, tự thử lại, tự tiêu ngân sách phục hồi (FR-014f).
    """
    sheet = _SKILL.read_text(encoding="utf-8").lower()
    for forbidden in ("curl", "agent_token", "authorization: bearer", "api_base_url"):
        assert forbidden not in sheet, (
            f"SKILL.md vẫn còn dạy {forbidden!r} — agent sẽ làm theo và ăn lỗi"
        )
