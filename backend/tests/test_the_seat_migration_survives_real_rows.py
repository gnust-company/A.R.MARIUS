"""Bản di trú ghế phải sống sót trên **dữ liệu đã có**, không chỉ trên ổ trống (T199).

Bài kiểm khớp lược đồ chạy chuỗi di trú lên một cơ sở dữ liệu rỗng, nên nó chứng minh được
hình dạng cuối cùng và **không chứng minh được gì** về phép chuyển dữ liệu. Cụm dịch vụ thật
cũng dựng lại từ ổ trống. Cả hai lối kiểm ấy đi vòng qua đúng chỗ một bản di trú hỏng: lượt
nâng cấp trên cụm đang chạy, một lần, lúc deploy.

Chỗ hỏng là phép nối đi qua **chuỗi mã vai**. Bảng `roles` không có ràng buộc duy nhất trên
`(project_id, key)`, và cửa onboarding không làm-duy-nhất khoá như cửa HTTP — agent soạn
roster có hai vai cùng tiêu đề là ra hai vai cùng khoá. Mỗi dòng ghế khi ấy nối ra hai dòng
vai, và cùng một `id` được chèn hai lần.
"""

from __future__ import annotations

import os
import sqlite3
import subprocess
import sys
import uuid
from datetime import datetime, timedelta
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]

# Ngay trước bản di trú ghế, để phép chuyển dữ liệu thật sự chạy.
_BEFORE_THE_SEAT_MIGRATION = "d3f7b2a6c1e8"


def _alembic(db_file: Path, target: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603 - fixed argv, test-only
        [sys.executable, "-m", "alembic", "upgrade", target],
        cwd=BACKEND_ROOT,
        env=os.environ | {"DATABASE_URL": f"sqlite+aiosqlite:///{db_file}"},
        capture_output=True,
        text=True,
        timeout=180,
    )


def _seed_a_project_with_two_roles_under_one_key(db_file: Path) -> tuple[str, str, str]:
    """Một dự án, hai vai trùng `key`, và một ghế trỏ vào cái khoá ấy.

    Trả về (id ghế, id vai tạo trước, id vai tạo sau) — vai tạo trước là vai mà mã đang chạy
    tự chọn khi tra theo khoá (`roles.list_by_project` xếp theo `created_at`), nên nó phải là
    vai mà bản di trú chọn.
    """
    ws, project = str(uuid.uuid4()), str(uuid.uuid4())
    older, newer = str(uuid.uuid4()), str(uuid.uuid4())
    agent, grant = str(uuid.uuid4()), str(uuid.uuid4())
    t0 = datetime(2026, 8, 1, 9, 0)

    con = sqlite3.connect(db_file)
    con.execute(
        "INSERT INTO workspaces (id, name, slug, owner_user_id) VALUES (?,?,?,?)",
        (ws, "WS", "ws", "patron-1"),
    )
    con.execute(
        "INSERT INTO projects (id, workspace_id, name, slug, status) VALUES (?,?,?,?,?)",
        (project, ws, "Apollo", "apollo", "operating"),
    )
    for role_id, made_at in ((older, t0), (newer, t0 + timedelta(minutes=5))):
        con.execute(
            "INSERT INTO roles (id, project_id, key, title, seats, is_leader, "
            "description, skill_ids, created_at) VALUES (?,?,?,?,?,?,?,?,?)",
            (role_id, project, "backend", "Backend", 1, 0, "Lo phần máy chủ.", "[]",
             made_at.isoformat(sep=" ")),
        )
    con.execute(
        "INSERT INTO mariuses (id, workspace_id, name, role, skills, adapter_type, "
        "adapter_config, skill_ids, liveness, invite_status, probe_attempts, backoff_step, "
        "skill_installs) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (agent, ws, "Dev", "Backend", "[]", "echo", "{}", "[]", "online", "approved",
         0, 0, "{}"),
    )
    con.execute(
        "INSERT INTO seat_grants (id, project_id, role_key, marius_id, status, "
        "granted_by_user_id, created_at) VALUES (?,?,?,?,?,?,?)",
        (grant, project, "backend", agent, "granted", "patron-1", t0.isoformat(sep=" ")),
    )
    con.commit()
    con.close()
    return grant, older, newer


def test_the_upgrade_survives_two_roles_sharing_one_key(tmp_path: Path) -> None:
    db_file = tmp_path / "dirty-roster.db"
    first = _alembic(db_file, _BEFORE_THE_SEAT_MIGRATION)
    assert first.returncode == 0, first.stderr or first.stdout

    grant, older, newer = _seed_a_project_with_two_roles_under_one_key(db_file)

    run = _alembic(db_file, "head")
    assert run.returncode == 0, (
        "lượt nâng cấp chết giữa chuỗi di trú:\n" + (run.stderr or run.stdout)
    )

    con = sqlite3.connect(db_file)
    try:
        rows = list(con.execute("SELECT id, role_id FROM seat_grants"))
    finally:
        con.close()
    assert len(rows) == 1, f"một ghế phải ra một dòng, ra {len(rows)}: {rows}"
    assert rows[0][0] == grant
    assert rows[0][1] == older, (
        "ghế phải sang đúng vai mà mã đang chạy vẫn chọn khi tra theo khoá — vai tạo trước"
    )
    assert rows[0][1] != newer


def test_a_seat_whose_role_key_matches_nothing_is_left_behind(tmp_path: Path) -> None:
    """Ghế trỏ vào một khoá không có vai nào đã không đọc được từ trước — mọi chỗ đọc đều nối
    nó sang `roles` rồi bỏ qua. Nó không sang bảng mới, và điều đó **không** được làm chết
    lượt nâng cấp."""
    db_file = tmp_path / "orphan-seat.db"
    assert _alembic(db_file, _BEFORE_THE_SEAT_MIGRATION).returncode == 0

    _seed_a_project_with_two_roles_under_one_key(db_file)
    con = sqlite3.connect(db_file)
    con.execute("UPDATE seat_grants SET role_key = 'khong-co-vai-nao'")
    con.commit()
    con.close()

    run = _alembic(db_file, "head")
    assert run.returncode == 0, run.stderr or run.stdout

    con = sqlite3.connect(db_file)
    try:
        assert list(con.execute("SELECT id FROM seat_grants")) == []
    finally:
        con.close()
