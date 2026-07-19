"""Project key — mã dự án ngắn kiểu JIRA (spec 01 §3.1, §4.1).

Một project mang một **key** viết hoa (vd ``CALC``), **duy nhất theo workspace**, làm phần
"KEY" trong mã task ``{KEY}-{seq}`` (vd ``CALC-7``). Key **bất biến** sau khi đặt.

Hàm thuần:

- :func:`suggest_project_key` — gợi ý từ tên dự án (4 chữ cái đầu, bỏ dấu + không-chữ);
  luôn trả về key hợp lệ (2–4 ký tự). Dùng làm giá trị mặc định khi caller không đặt key.
- :func:`validate_project_key` — kiểm format; ném :class:`InvalidProjectKey` nếu sai.
- :data:`PROJECT_KEY_RE` — regex format: bắt đầu bằng chữ, 2–10 ký tự ``[A-Z0-9]``.
"""

from __future__ import annotations

import re
import unicodedata

# Bắt đầu bằng chữ cái, theo sau là 1–9 ký tự [A-Z0-9] → tổng 2–10 ký tự.
PROJECT_KEY_RE = re.compile(r"^[A-Z][A-Z0-9]{1,9}$")
_SUGGEST_MAX_LEN = 4
_FALLBACK_KEY = "PROJ"


class InvalidProjectKey(ValueError):
    """Project key sai format (phải khớp ``^[A-Z][A-Z0-9]{1,9}$``)."""


def suggest_project_key(project_name: str) -> str:
    """Gợi ý key từ tên dự án: 4 chữ cái đầu, viết hoa, bỏ dấu + không-chữ.

    Luôn trả về key hợp lệ (≥ 2 ký tự, bắt đầu bằng chữ):
    - ``"Calculator"`` → ``"CALC"``
    - ``"A.R. MARIUS"`` → ``"ARMA"``
    - ``"Tính toán"`` → ``"TINH"``; ``"Đồng bộ"`` → ``"DONG"``
    - ``"Go"`` → ``"GO"``; ``"A"`` → ``"AX"`` (đệm cho đủ 2)
    - ``""`` / ``"...!!!"`` → ``"PROJ"`` (dự phòng)
    """
    # "đ"/"Đ" không tách được bằng NFKD → đổi tay thành "d" trước khi chuẩn hoá.
    normalized = (project_name or "").replace("đ", "d").replace("Đ", "d")
    decomposed = unicodedata.normalize("NFKD", normalized)
    letters = [c for c in decomposed if c.isascii() and c.isalpha()]
    key = "".join(letters[:_SUGGEST_MAX_LEN]).upper() or _FALLBACK_KEY
    if len(key) < 2:
        key = key + "X" * (2 - len(key))
    return key


def validate_project_key(key: str) -> str:
    """Trả về key đã chuẩn hoá (viết hoa) nếu hợp lệ; ngược lại ném :class:`InvalidProjectKey`."""
    normalized = key.strip().upper()
    if not PROJECT_KEY_RE.match(normalized):
        raise InvalidProjectKey(
            f"project key must be 2–10 uppercase chars, starting with a letter (got {key!r})."
        )
    return normalized
