"""Bản di trú `a5d2c9f7e134` chạy trên cơ sở dữ liệu **đã có dữ liệu** (spec 001 FR-056).

Cả bộ kiểm còn lại dựng lược đồ thẳng từ khai báo mô hình, nên chúng chứng minh hành vi
**sau** khi đổi và không chứng minh gì về đường **đi qua** chỗ đổi. Riêng bản di trú này
mang một mệnh đề lọc cho mỗi trạng thái, và một lỗi gõ trong bất kỳ mệnh đề nào cũng không
làm hỏng lược đồ — nó chỉ làm hỏng *dữ liệu*, đúng một lần, trên một cơ sở dữ liệu đang
chạy mà không ai xem lại được.

Cái giá của lỗi đó rất lệch về một phía. Bỏ sót một đầu việc đang mở nghĩa là nó lên bảng
với động cơ rỗng, và vòng quét canh gác đọc động cơ rỗng đúng là **đã bị đánh rơi** — nên
lượt quét đầu tiên sau khi nâng cấp sẽ rung chuông trên cả bảng cùng một lúc, đúng thứ mà
đoạn backfill sinh ra để tránh. Còn quét quá tay sang việc *đã xong* thì đặt một cái hẹn
lên thứ không còn ai chờ.

Bài này chạy chuỗi di trú thật, trên dữ liệu dựng như đêm trước khi nâng cấp.
"""

from __future__ import annotations

import os
import subprocess
import sys
import uuid
from pathlib import Path

from sqlalchemy import create_engine, text

BACKEND_ROOT = Path(__file__).resolve().parents[1]
BEFORE = "d7b3e9c2a840"  # bản ngay trước khi lưới an toàn được dựng

# Sáu đầu việc, sáu hình dạng dữ liệu mà đoạn backfill phải phân biệt được:
BLOCKED = uuid.uuid4()  # chờ một đầu việc khác — cái chặn nó có dòng riêng
IN_REVIEW = uuid.uuid4()  # chờ một quyết định — thang nhắc lo phần giục
TODO = uuid.uuid4()  # đoán là có lệnh đánh thức, nên phải kèm hạn ngắn
IN_PROGRESS = uuid.uuid4()  # như trên
ALREADY_DRIVEN = uuid.uuid4()  # đã có động cơ từ đợt trước — không được ghi đè
DONE = uuid.uuid4()  # đã đóng — không ai canh, nên không được gắn động cơ


def _alembic(db_file: Path, target: str) -> None:
    run = subprocess.run(  # noqa: S603 - fixed argv, test-only
        [sys.executable, "-m", "alembic", "upgrade", target],
        cwd=BACKEND_ROOT,
        env=os.environ | {"DATABASE_URL": f"sqlite+aiosqlite:///{db_file}"},
        capture_output=True,
        text=True,
        timeout=180,
    )
    assert run.returncode == 0, run.stderr or run.stdout


def _seed(db_file: Path) -> None:
    """Dựng lại một bảng đầu việc như nó trông vào đêm trước khi nâng cấp."""
    engine = create_engine(f"sqlite:///{db_file}")
    project = uuid.uuid4()
    try:
        with engine.begin() as cx:
            for task_id, status, drive in (
                (BLOCKED, "blocked", None),
                (IN_REVIEW, "in_review", None),
                (TODO, "todo", None),
                (IN_PROGRESS, "in_progress", None),
                (ALREADY_DRIVEN, "in_progress", "run_active"),
                (DONE, "done", None),
            ):
                cx.execute(
                    text(
                        "INSERT INTO tasks (id, project_id, title, status, priority, "
                        "stalled, drive) VALUES (:i, :p, :t, :s, 'medium', 0, :d)"
                    ),
                    {
                        "i": str(task_id),
                        "p": str(project),
                        "t": "Kết xuất báo cáo",
                        "s": status,
                        "d": drive,
                    },
                )
    finally:
        engine.dispose()


def _drive(db_file: Path, task_id: uuid.UUID) -> tuple[str | None, str | None]:
    engine = create_engine(f"sqlite:///{db_file}")
    try:
        with engine.begin() as cx:
            row = cx.execute(
                text("SELECT drive, drive_expires_at FROM tasks WHERE id = :t"),
                {"t": str(task_id)},
            ).one()
    finally:
        engine.dispose()
    return row[0], (str(row[1]) if row[1] is not None else None)


def _migrated(tmp_path: Path) -> Path:
    db_file = tmp_path / "drive-backfill.db"
    _alembic(db_file, BEFORE)
    _seed(db_file)
    _alembic(db_file, "head")
    return db_file


def test_every_open_task_comes_out_of_the_upgrade_with_a_drive(tmp_path: Path) -> None:
    """Điều bất biến chính: không đầu việc đang mở nào bước qua bản nâng cấp mà tay không.

    Động cơ rỗng trên một đầu việc đang mở chính là định nghĩa của *đã bị đánh rơi*, nên
    một mệnh đề lọc gõ sót không làm hỏng lược đồ — nó làm lượt quét đầu tiên sau khi nâng
    cấp rung chuông trên toàn bộ bảng cùng lúc.
    """
    db_file = _migrated(tmp_path)
    engine = create_engine(f"sqlite:///{db_file}")
    try:
        with engine.begin() as cx:
            driveless = cx.execute(
                text(
                    "SELECT count(*) FROM tasks WHERE drive IS NULL AND status IN "
                    "('todo', 'in_progress', 'in_review', 'blocked')"
                )
            ).scalar_one()
    finally:
        engine.dispose()

    assert driveless == 0, (
        "còn đầu việc đang mở không có động cơ sau khi nâng cấp — lượt quét đầu tiên sẽ "
        "báo đình trệ cho cả bảng cùng một lúc"
    )


def test_the_two_waits_that_end_on_an_event_get_no_clock(tmp_path: Path) -> None:
    """*Bị chặn* và *chờ rà soát* chờ một sự kiện, không chờ hết giờ.

    Gắn hạn cho chúng là dựng thêm một cái chuông thứ hai cho thứ đã có người canh: cái
    chặn có dòng riêng của nó, còn thang nhắc lo phần giục người quyết.
    """
    db_file = _migrated(tmp_path)

    assert _drive(db_file, BLOCKED) == ("blocked_by_task", None)
    assert _drive(db_file, IN_REVIEW) == ("waiting_patron", None)


def test_the_two_guessed_statuses_get_a_short_deadline(tmp_path: Path) -> None:
    """*Chờ làm* và *đang làm* là chỗ bản di trú **đoán**, nên nó phải đoán có hạn.

    Nếu lệnh đánh thức thật sự đang chờ, tầng nghiệp vụ sẽ làm mới động cơ trước khi hạn
    này lapse. Nếu không có gì chờ cả — tức đầu việc đã bị rơi từ trước lúc nâng cấp — thì
    hạn hết trong vài phút và chuông rung lúc đó, trên một dịch vụ đang chạy, từng đầu việc
    một, thay vì cả bảng trong giây đầu tiên.
    """
    db_file = _migrated(tmp_path)

    for task_id in (TODO, IN_PROGRESS):
        drive, expires = _drive(db_file, task_id)
        assert drive == "wake_scheduled", task_id
        assert expires is not None, (
            "đoán mà không kèm hạn thì cái đoán đó không bao giờ bị lật lại"
        )


def test_a_drive_written_by_an_earlier_release_is_left_alone(tmp_path: Path) -> None:
    """Đối chứng: bản backfill chỉ chạm vào chỗ trống.

    Động cơ đã được ghi từ đợt trước là câu trả lời **thật** — nó biết những gì bản di trú
    không nhìn thấy được. Ghi đè lên nó là đổi một sự thật lấy một phỏng đoán.
    """
    assert _drive(_migrated(tmp_path), ALREADY_DRIVEN) == ("run_active", None)


def test_a_closed_task_is_not_given_something_to_wait_for(tmp_path: Path) -> None:
    """Đối chứng thứ hai, ở phía kia: quét quá tay cũng là hỏng.

    Việc đã đóng thì không ai còn chờ nó. Gắn động cơ cho nó là dựng một cái hẹn lên thứ
    không có gì sẽ tới, và vòng quét sẽ phải học cách bỏ qua chính dữ liệu nó vừa ghi ra.
    """
    assert _drive(_migrated(tmp_path), DONE) == (None, None)
