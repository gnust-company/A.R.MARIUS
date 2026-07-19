"""Quy tắc project key — hàm thuần trong ``domain/services/project_key.py`` (spec 01 §3.1).

Key JIRA-style: 2–10 ký tự viết hoa, bắt đầu bằng chữ. Suggest lấy 4 chữ cái đầu tên dự án.
"""

from __future__ import annotations

import pytest

from armarius.domain.services.project_key import (
    InvalidProjectKey,
    suggest_project_key,
    validate_project_key,
)

# ── suggest_project_key ──────────────────────────────────────────────────────


def test_suggest_takes_first_four_letters_of_a_single_word():
    assert suggest_project_key("Calculator") == "CALC"


def test_suggest_strips_separators_and_non_letters():
    assert suggest_project_key("A.R. MARIUS") == "ARMA"


def test_suggest_strips_vietnamese_diacritics_including_đ():
    assert suggest_project_key("Tính toán") == "TINH"
    assert suggest_project_key("Đồng bộ") == "DONG"


def test_suggest_short_name_is_padded_to_two_chars():
    assert suggest_project_key("A") == "AX"
    assert suggest_project_key("Go") == "GO"


def test_suggest_empty_or_symbols_falls_back_to_proj():
    assert suggest_project_key("") == "PROJ"
    assert suggest_project_key("...!!!") == "PROJ"


# ── validate_project_key ──────────────────────────────────────────────────────


def test_validate_uppercases_then_accepts_valid_keys():
    assert validate_project_key("calc") == "CALC"
    assert validate_project_key("PROJ1") == "PROJ1"
    assert validate_project_key("ab") == "AB"  # min length 2


def test_validate_rejects_too_short():
    with pytest.raises(InvalidProjectKey):
        validate_project_key("A")


def test_validate_rejects_leading_digit():
    with pytest.raises(InvalidProjectKey):
        validate_project_key("1UP")


def test_validate_rejects_too_long():
    with pytest.raises(InvalidProjectKey):
        validate_project_key("ELEVENCHARS")  # 11 chars
