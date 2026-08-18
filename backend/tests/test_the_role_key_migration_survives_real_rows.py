"""Bản di trú T202 chạy trên **dòng thật đã bẩn**, không phải trên cơ sở dữ liệu rỗng.

Bài kiểm khớp lược đồ và lượt dựng lại cả cụm đều bắt đầu từ ổ đĩa trắng, nên chúng chỉ soi
được *hình dạng* bản di trú làm ra, không soi được *đường dữ liệu* đi qua nó. Đúng nửa không
được soi ấy đã làm hỏng bản di trú ghế ở lượt rà trước.

Ba loại dòng bẩn được gieo ở đây, đều là dòng mà cửa onboarding thật có thể ghi ra:

  * hai vai cùng khoá trong một dự án — chuyện đã có, và là lý do bài này tồn tại;
  * ba vai cùng khoá, để chắc phép đánh số chạy tiếp chứ không dừng ở lần đổi thứ nhất;
  * hai vai cùng khoá **cộng với** một vai đã mang sẵn khoá mà phép đánh số định lấy.

Chuyện quan trọng nhất phải giữ: ghế **không được xê dịch**. Từ T199 ghế trỏ vào `role_id`,
nên đổi khoá không đẩy ai khỏi chỗ ngồi. Nếu ghế còn trỏ theo khoá thì bản di trú này sẽ âm
thầm chuyển người sang vai khác, nên nó được kiểm thành một điều riêng.
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

#: Ngay trước bản di trú khoá vai, để phép đổi tên thật sự chạy.
_BEFORE = "e9c2a4d7f0b3"


def _alembic(db_file: Path, target: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603 - fixed argv, test-only
        [sys.executable, "-m", "alembic", "upgrade", target],
        cwd=BACKEND_ROOT,
        env=os.environ | {"DATABASE_URL": f"sqlite+aiosqlite:///{db_file}"},
        capture_output=True,
        text=True,
        timeout=180,
    )


def _base(con: sqlite3.Connection) -> tuple[str, str]:
    ws, project = str(uuid.uuid4()), str(uuid.uuid4())
    con.execute(
        "INSERT INTO workspaces (id, name, slug, owner_user_id) VALUES (?,?,?,?)",
        (ws, "WS", "ws", "patron-1"),
    )
    con.execute(
        "INSERT INTO projects (id, workspace_id, name, slug, status) VALUES (?,?,?,?,?)",
        (project, ws, "Apollo", "apollo", "operating"),
    )
    return ws, project


def _role(con: sqlite3.Connection, project: str, key: str, made_at: datetime) -> str:
    role_id = str(uuid.uuid4())
    con.execute(
        "INSERT INTO roles (id, project_id, key, title, seats, is_leader, description, "
        "skill_ids, created_at) VALUES (?,?,?,?,?,?,?,?,?)",
        (role_id, project, key, key.title(), 1, 0, "Mô tả.", "[]",
         made_at.isoformat(sep=" ")),
    )
    return role_id


def _keys(db_file: Path, project: str) -> dict[str, str]:
    con = sqlite3.connect(db_file)
    rows = con.execute(
        "SELECT id, key FROM roles WHERE project_id = ? ORDER BY created_at, id", (project,)
    ).fetchall()
    con.close()
    return {rid: key for rid, key in rows}


def test_two_roles_sharing_a_key_end_up_with_two_keys(tmp_path: Path) -> None:
    db_file = tmp_path / "a.db"
    assert _alembic(db_file, _BEFORE).returncode == 0
    t0 = datetime(2026, 8, 1, 9, 0)
    con = sqlite3.connect(db_file)
    _, project = _base(con)
    older = _role(con, project, "backend", t0)
    newer = _role(con, project, "backend", t0 + timedelta(minutes=5))
    con.commit()
    con.close()

    run = _alembic(db_file, "head")
    assert run.returncode == 0, run.stderr

    keys = _keys(db_file, project)
    # Vai tạo trước giữ khoá gốc: đó là vai mà mã đang chạy vẫn trả về khi tra theo khoá,
    # nên đổi nó mới là thứ làm đổi hành vi.
    assert keys[older] == "backend"
    assert keys[newer] == "backend2"


def test_the_renumbering_keeps_going_past_the_first_clash(tmp_path: Path) -> None:
    db_file = tmp_path / "b.db"
    assert _alembic(db_file, _BEFORE).returncode == 0
    t0 = datetime(2026, 8, 1, 9, 0)
    con = sqlite3.connect(db_file)
    _, project = _base(con)
    ids = [_role(con, project, "backend", t0 + timedelta(minutes=i)) for i in range(3)]
    con.commit()
    con.close()

    assert _alembic(db_file, "head").returncode == 0
    keys = _keys(db_file, project)
    assert [keys[i] for i in ids] == ["backend", "backend2", "backend3"]


def test_a_rename_does_not_land_on_a_key_somebody_already_holds(tmp_path: Path) -> None:
    """Dự án đã có sẵn `backend2` do người đặt tay, nên `backend2` không còn trống."""
    db_file = tmp_path / "c.db"
    assert _alembic(db_file, _BEFORE).returncode == 0
    t0 = datetime(2026, 8, 1, 9, 0)
    con = sqlite3.connect(db_file)
    _, project = _base(con)
    older = _role(con, project, "backend", t0)
    newer = _role(con, project, "backend", t0 + timedelta(minutes=5))
    handmade = _role(con, project, "backend2", t0 + timedelta(minutes=1))
    con.commit()
    con.close()

    assert _alembic(db_file, "head").returncode == 0
    keys = _keys(db_file, project)
    assert keys[older] == "backend"
    assert keys[handmade] == "backend2"
    assert keys[newer] == "backend3"
    assert len(set(keys.values())) == 3


def test_renaming_a_role_does_not_move_anybody_out_of_their_seat(tmp_path: Path) -> None:
    db_file = tmp_path / "d.db"
    assert _alembic(db_file, _BEFORE).returncode == 0
    t0 = datetime(2026, 8, 1, 9, 0)
    con = sqlite3.connect(db_file)
    ws, project = _base(con)
    older = _role(con, project, "backend", t0)
    newer = _role(con, project, "backend", t0 + timedelta(minutes=5))
    agent, grant = str(uuid.uuid4()), str(uuid.uuid4())
    con.execute(
        "INSERT INTO mariuses (id, workspace_id, name, role, skills, adapter_type, "
        "adapter_config, skill_ids, liveness, invite_status, probe_attempts, backoff_step, "
        "skill_installs) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (agent, ws, "Dev", "Backend", "[]", "echo", "{}", "[]", "online", "approved",
         0, 0, "{}"),
    )
    # Ghế trỏ vào **vai tạo sau** — chính là vai sẽ bị đổi khoá.
    con.execute(
        "INSERT INTO seat_grants (id, project_id, role_id, marius_id, granted_by_user_id, "
        "granted_at, created_at) VALUES (?,?,?,?,?,?,?)",
        (grant, project, newer, agent, "patron-1", t0.isoformat(sep=" "),
         t0.isoformat(sep=" ")),
    )
    con.commit()
    con.close()

    assert _alembic(db_file, "head").returncode == 0
    con = sqlite3.connect(db_file)
    seat_role = con.execute(
        "SELECT role_id FROM seat_grants WHERE id = ?", (grant,)
    ).fetchone()[0]
    con.close()
    assert seat_role == newer, "đổi khoá vai đã đẩy người ngồi sang vai khác"
    assert _keys(db_file, project)[older] == "backend"
