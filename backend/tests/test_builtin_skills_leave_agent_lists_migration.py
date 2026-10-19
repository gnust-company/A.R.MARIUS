"""Bản di trú dọn skill dựng sẵn khỏi danh sách của agent, trên dữ liệu đã có (spec 003 FR-123).

Bài khớp lược đồ chạy chuỗi di trú trên ổ trống, nên nó không chứng minh gì về một phép chuyển
**dữ liệu**. Bài này gieo dữ liệu ở revision ngay trước, rồi nâng lên head.

Hai thứ dễ hỏng nhất:

  1. SQLite giữ UUID ở **hai** dạng: 32 ký tự hex (ORM ghi) và có gạch nối (các bản di trú cũ
     và dữ liệu gieo tay ghi). Bản di trú phải khớp cả hai, không được lẳng lặng bỏ sót dạng nào.
  2. Chỉ skill dựng sẵn bị bỏ. Skill người dùng tự thêm, và agent không gian làm việc khác, đứng
     yên.
"""

from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
import uuid
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]

_BEFORE = "b8d2f4a6c1e3"


def _alembic(db_file: Path, target: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603 - fixed argv, test-only
        [sys.executable, "-m", "alembic", "upgrade", target],
        cwd=BACKEND_ROOT,
        env=os.environ | {"DATABASE_URL": f"sqlite+aiosqlite:///{db_file}"},
        capture_output=True,
        text=True,
        timeout=180,
    )


def _workspace(con: sqlite3.Connection, ws: str, slug: str) -> None:
    con.execute(
        "INSERT INTO workspaces (id, name, slug, owner_user_id) VALUES (?,?,?,?)",
        (ws, slug, slug, "patron-1"),
    )


def _skill(con: sqlite3.Connection, skill: str, ws: str, name: str, source: str) -> None:
    con.execute(
        "INSERT INTO skills (id, workspace_id, slug, name, description, source, source_url, "
        "files) VALUES (?,?,?,?,?,?,?,?)",
        (skill, ws, name.lower().replace(" ", "-"), name, "", source, "", "{}"),
    )


def _agent(
    con: sqlite3.Connection, agent: str, ws: str, name: str, skill_ids: list[str], names: list[str]
) -> None:
    con.execute(
        "INSERT INTO mariuses (id, workspace_id, name, role, skills, adapter_type, "
        "adapter_config, skill_ids, liveness) VALUES (?,?,?,?,?,?,?,?,?)",
        (agent, ws, name, "", json.dumps(names), "daemon", "{}", json.dumps(skill_ids),
         "offline"),
    )


def _lists(db_file: Path) -> dict[str, tuple[list[str], list[str]]]:
    con = sqlite3.connect(db_file)
    try:
        return {
            name: (json.loads(ids), json.loads(names))
            for name, ids, names in con.execute("SELECT name, skill_ids, skills FROM mariuses")
        }
    finally:
        con.close()


def test_built_ins_leave_every_list_in_both_ways_sqlite_keeps_an_id(tmp_path: Path) -> None:
    """Hai không gian làm việc, mỗi cái một kiểu ghi.

    `orm` ghi như ORM ghi trên SQLite: mọi cột UUID là 32 ký tự hex — trong khi `skill_ids` (một
    cột JSON) giữ `str(id)`, có gạch nối. Đây là hỗn hợp có thật trong mọi DB SQLite đang chạy, và
    là chỗ một phép so sánh thô bỏ sót. `tay` ghi toàn bộ có gạch nối, như dữ liệu gieo tay.
    """
    db_file = tmp_path / "skills-on-agents.db"
    first = _alembic(db_file, _BEFORE)
    assert first.returncode == 0, first.stderr or first.stdout

    orm_ws, hand_ws = uuid.uuid4(), uuid.uuid4()
    orm_builtin, orm_own = uuid.uuid4(), uuid.uuid4()
    hand_builtin, hand_own = uuid.uuid4(), uuid.uuid4()
    con = sqlite3.connect(db_file)
    # ── ghi kiểu ORM: cột UUID 32 hex, danh sách JSON có gạch nối
    _workspace(con, orm_ws.hex, "orm")
    _skill(con, orm_builtin.hex, orm_ws.hex, "Talking to Armarius", "builtin")
    _skill(con, orm_own.hex, orm_ws.hex, "Viết báo cáo", "manual")
    _agent(con, uuid.uuid4().hex, orm_ws.hex, "Cassia", [str(orm_builtin), str(orm_own)],
           ["Talking to Armarius", "Viết báo cáo"])
    _agent(con, uuid.uuid4().hex, orm_ws.hex, "Nona", [str(orm_own)], ["Viết báo cáo"])
    # ── ghi tay: có gạch nối ở mọi chỗ
    _workspace(con, str(hand_ws), "tay")
    _skill(con, str(hand_builtin), str(hand_ws), "Talking to Armarius", "builtin")
    _skill(con, str(hand_own), str(hand_ws), "Dịch thuật", "manual")
    _agent(con, str(uuid.uuid4()), str(hand_ws), "Decima", [str(hand_builtin)],
           ["Talking to Armarius"])
    _agent(con, str(uuid.uuid4()), str(hand_ws), "Morta", [str(hand_own)], ["Dịch thuật"])
    con.commit()
    con.close()

    run = _alembic(db_file, "head")
    assert run.returncode == 0, run.stderr or run.stdout

    lists = _lists(db_file)
    assert lists["Cassia"] == ([str(orm_own)], ["Viết báo cáo"]), (
        "id 32 hex trên bảng skills phải khớp với id có gạch nối trong danh sách của agent"
    )
    assert lists["Nona"] == ([str(orm_own)], ["Viết báo cáo"])
    assert lists["Decima"] == ([], [])
    assert lists["Morta"] == ([str(hand_own)], ["Dịch thuật"])


def test_a_database_with_no_built_ins_goes_up_untouched(tmp_path: Path) -> None:
    db_file = tmp_path / "no-builtins.db"
    assert _alembic(db_file, _BEFORE).returncode == 0

    ws, own = str(uuid.uuid4()), str(uuid.uuid4())
    con = sqlite3.connect(db_file)
    _workspace(con, ws, "mot")
    _skill(con, own, ws, "Viết báo cáo", "manual")
    _agent(con, str(uuid.uuid4()), ws, "Cassia", [own], ["Viết báo cáo"])
    con.commit()
    con.close()

    run = _alembic(db_file, "head")
    assert run.returncode == 0, run.stderr or run.stdout
    assert _lists(db_file)["Cassia"] == ([own], ["Viết báo cáo"])
