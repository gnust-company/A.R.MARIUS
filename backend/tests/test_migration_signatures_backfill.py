"""Bản di trú `d7b3e9c2a840` chạy trên cơ sở dữ liệu **đã có dữ liệu** (spec 001 FR-041a).

Mọi bài kiểm khác trong kho này dựng lược đồ thẳng từ khai báo mô hình, nên chúng chứng
minh được hành vi **sau** khi đổi, và không chứng minh được gì về đường **đi qua** chỗ đổi.
Một cơ sở dữ liệu đang chạy không dựng lại từ đầu — nó được nâng cấp, mang theo những dòng
đã có từ trước. Chỗ đó có luật riêng, và luật đó chỉ kiểm được ở đây.

Điều bất biến mà bài này canh: **sau khi nâng cấp, không đầu việc nào còn mang một lời từ
chối đang hiệu lực.** Một lời từ chối luôn đã đẩy đầu việc về làm lại — đó chính là nghĩa
của nó — nên nó không bao giờ còn nói cho bản đang nằm trên bàn. Nếu nó sót lại, đầu việc
đó **không bao giờ đóng được nữa**: cổng đóng việc phủ quyết ngay khi thấy một lời từ chối,
mà hai chữ ký mới thì vẫn đủ, nên không cửa nào trong hệ nói được vì sao nó kẹt.
"""

from __future__ import annotations

import os
import subprocess
import sys
import uuid
from pathlib import Path

from sqlalchemy import create_engine, text

BACKEND_ROOT = Path(__file__).resolve().parents[1]
BEFORE = "c4f1a8b3d2e7"  # bản ngay trước khi số vòng bị bỏ

# Bốn đầu việc, bốn hình dạng dữ liệu đáng lo:
REWORKED = uuid.uuid4()  # đã bị trả về, đã sửa, đang nộp lại — ca lọt lưới
FIRST_PASS = uuid.uuid4()  # lần đầu vào rà soát, chưa ai trả về
CLOSED = uuid.uuid4()  # đã đóng bằng đủ hai chữ ký
BACK_IN_PROGRESS = uuid.uuid4()  # đã rời rà soát, đang làm lại


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
    """Dựng lại một cơ sở dữ liệu như nó trông vào đêm trước khi nâng cấp."""
    engine = create_engine(f"sqlite:///{db_file}")
    project = uuid.uuid4()
    try:
        with engine.begin() as cx:
            for task_id, status in (
                (REWORKED, "in_review"),
                (FIRST_PASS, "in_review"),
                (CLOSED, "done"),
                (BACK_IN_PROGRESS, "in_progress"),
            ):
                cx.execute(
                    text(
                        "INSERT INTO tasks (id, project_id, title, status, priority, "
                        "stalled) VALUES (:i, :p, :t, :s, 'medium', 0)"
                    ),
                    {"i": str(task_id), "p": str(project), "t": "Kết xuất báo cáo",
                     "s": status},
                )

            def sign(task_id, kind, result, at, round_no=1, reason=None):
                cx.execute(
                    text(
                        "INSERT INTO task_approvals (id, task_id, round, signer_kind, "
                        "result, reason, is_auto, signed_at) VALUES "
                        "(:i, :t, :r, :k, :res, :why, 0, :at)"
                    ),
                    {"i": str(uuid.uuid4()), "t": str(task_id), "r": round_no,
                     "k": kind, "res": result, "why": reason,
                     "at": f"2026-08-01 10:{at:02d}:00"},
                )

            # Đã bị trả về ở vòng một, thợ sửa xong và nộp lại; chưa ai ký cho bản mới.
            sign(REWORKED, "leader", "approve", 0)
            sign(REWORKED, "patron", "reject", 5, reason="Thiếu đối chiếu sổ cái.")
            # Lần đầu vào rà soát: Trưởng dự án đã ký, còn chờ người chủ.
            sign(FIRST_PASS, "leader", "approve", 0)
            # Đã đóng: đủ hai chữ ký, không ai trả về.
            sign(CLOSED, "leader", "approve", 0)
            sign(CLOSED, "patron", "approve", 5)
            # Đã rời rà soát bằng tay, đang làm lại.
            sign(BACK_IN_PROGRESS, "leader", "approve", 0)
    finally:
        engine.dispose()


def _rows(db_file: Path, task_id: uuid.UUID) -> list[tuple[str, str, int]]:
    engine = create_engine(f"sqlite:///{db_file}")
    try:
        with engine.begin() as cx:
            return [
                (r[0], r[1], int(r[2]))
                for r in cx.execute(
                    text(
                        "SELECT signer_kind, result, superseded FROM task_approvals "
                        "WHERE task_id = :t ORDER BY signed_at"
                    ),
                    {"t": str(task_id)},
                ).all()
            ]
    finally:
        engine.dispose()


def _migrated(tmp_path: Path) -> Path:
    db_file = tmp_path / "backfill.db"
    _alembic(db_file, BEFORE)
    _seed(db_file)
    _alembic(db_file, "head")
    return db_file


def test_the_migration_leaves_no_rejection_still_in_force(tmp_path: Path) -> None:
    """Điều bất biến chính, và ca mà bản backfill đầu tiên để lọt.

    Đầu việc đã bị trả về rồi nộp lại thì lúc nâng cấp vẫn đang ở *chờ rà soát*, nên một
    phép lọc theo trạng thái sẽ tha cho nó — và tha luôn cả lời từ chối cũ nằm trong sổ.
    Sau đó hai bên ký đủ cho bản mới, cổng đóng việc vẫn phủ quyết vì thấy lời từ chối,
    còn bộ điều phối thì không thấy thiếu chữ ký nào nên không báo gì. Kẹt, và im.
    """
    db_file = _migrated(tmp_path)
    engine = create_engine(f"sqlite:///{db_file}")
    try:
        with engine.begin() as cx:
            live_rejections = cx.execute(
                text(
                    "SELECT count(*) FROM task_approvals "
                    "WHERE result = 'reject' AND superseded = 0"
                )
            ).scalar_one()
    finally:
        engine.dispose()

    assert live_rejections == 0, (
        "một lời từ chối còn hiệu lực sau khi nâng cấp sẽ khoá đầu việc đó khỏi *xong* "
        "vĩnh viễn, mà không cửa nào trong hệ báo được vì sao"
    )


def test_the_migration_keeps_the_signatures_that_closed_a_task(tmp_path: Path) -> None:
    """Đối chứng. Việc đã đóng thì lần rà soát đóng nó vẫn là lần đang đứng.

    Không có luật này thì bản di trú sẽ viết lại lịch sử của mọi việc đã xong.
    """
    rows = _rows(_migrated(tmp_path), CLOSED)

    assert rows and all(superseded == 0 for _, _, superseded in rows), rows


def test_the_migration_retires_the_signatures_of_work_being_redone(
    tmp_path: Path,
) -> None:
    """Đối chứng thứ hai: đầu việc đã rời rà soát thì chữ ký cũ phải hết hiệu lực.

    Đây là ca bản backfill đầu tiên đã làm đúng; giữ bài kiểm để bản vá không đánh mất nó.
    """
    rows = _rows(_migrated(tmp_path), BACK_IN_PROGRESS)

    assert rows and all(superseded == 1 for _, _, superseded in rows), rows


def test_a_task_awaiting_its_second_signature_starts_the_review_over(
    tmp_path: Path,
) -> None:
    """Chọn hỏng theo hướng *đóng chặt*, không theo hướng *kẹt cứng*.

    Đầu việc đang chờ chữ ký thứ hai sẽ phải xin lại chữ ký thứ nhất — phiền đúng một
    lần, ngay lúc nâng cấp, và tự khỏi: bộ điều phối thấy thiếu chữ ký Trưởng dự án nên
    gọi đúng người tới ký. Cái giá của phương án tinh vi hơn là một đầu việc kẹt vĩnh
    viễn nếu suy luận sai, và một bản di trú chỉ chạy đúng một lần trên dữ liệu không ai
    xem lại được là chỗ tệ nhất để đặt cược vào suy luận tinh vi.
    """
    rows = _rows(_migrated(tmp_path), FIRST_PASS)

    assert rows and all(superseded == 1 for _, _, superseded in rows), rows
