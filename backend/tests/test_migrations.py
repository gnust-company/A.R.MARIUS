"""Sprint 3 — Alembic 0002 applies and reverses cleanly on a throwaway database.

Drives the real `alembic` command stack (env.py → async engine), pointed at an isolated
SQLite file via `settings.database_url`. A plain (sync) test so env.py's own
`asyncio.run` has no running loop to collide with.
"""

from __future__ import annotations

from alembic import command
from sqlalchemy import create_engine, inspect

from armarius.infrastructure.database.migrations import _config
from armarius.shared.config import settings

_SPRINT3 = "468899ef9a27"
_BASELINE = "a40098b66ac7"


def test_migrations_upgrade_head_then_downgrade_base(tmp_path, monkeypatch) -> None:
    db = tmp_path / "mig.db"
    monkeypatch.setattr(settings, "database_url", f"sqlite+aiosqlite:///{db}")
    cfg = _config()

    command.upgrade(cfg, "head")

    insp = inspect(create_engine(f"sqlite:///{db}"))
    tables = set(insp.get_table_names())
    assert {"roles", "seat_grants", "labels", "project_leader_conversations"} <= tables
    project_cols = {c["name"] for c in insp.get_columns("projects")}
    assert {"status", "objective", "settings", "created_by_user_id"} <= project_cols
    marius_cols = {c["name"] for c in insp.get_columns("mariuses")}
    assert {"invite_status", "probe_attempts", "next_probe_at", "turn_started_at"} <= marius_cols
    insp.bind.dispose()

    # Down to the baseline: Sprint-3 objects vanish, the baseline tables remain.
    command.downgrade(cfg, _BASELINE)
    insp2 = inspect(create_engine(f"sqlite:///{db}"))
    tables2 = set(insp2.get_table_names())
    assert "roles" not in tables2
    assert "seat_grants" not in tables2
    assert "labels" not in tables2
    assert "commission_sessions" not in tables2
    assert "projects" in tables2
    assert "status" not in {c["name"] for c in insp2.get_columns("projects")}
    insp2.bind.dispose()

    # And all the way back to an empty schema.
    command.downgrade(cfg, "base")
    insp3 = inspect(create_engine(f"sqlite:///{db}"))
    assert "projects" not in set(insp3.get_table_names())
    insp3.bind.dispose()


def test_stepping_down_one_revision_from_head_is_never_ambiguous(tmp_path, monkeypatch) -> None:
    """Lùi **một nấc** là lệnh người ta gõ lúc nửa đêm khi bản deploy vừa hỏng.

    Bài `upgrade head` rồi `downgrade base` ở trên **không** thấy được lỗi này: một mối nối
    (merge revision) vẫn cho `head` đúng một nghĩa và vẫn lùi thẳng về `base` được, nhưng
    `downgrade -1` thì chết với *Ambiguous walk* vì từ mối nối có hai đường đi xuống.

    Đây là đường mà cả nghìn bài khác không đi qua: bộ kiểm dựng bảng thẳng từ metadata của
    SQLAlchemy, nên đồ thị migration có gãy cũng không bài nào đỏ.
    """
    db = tmp_path / "step.db"
    monkeypatch.setattr(settings, "database_url", f"sqlite+aiosqlite:///{db}")
    cfg = _config()

    command.upgrade(cfg, "head")
    command.downgrade(cfg, "-1")  # Ambiguous walk ở đây nếu head nằm trên một mối nối.


def test_the_revision_graph_stays_a_single_line() -> None:
    """Một head là chưa đủ: chuỗi phải **thẳng**, không rẽ và không có mối nối nào.

    Hai lỗi đã xảy ra thật đều nằm trong hình dạng của đồ thị chứ không trong nội dung
    revision nào: một bản mới chỉ vào sai cha (thành hai head), rồi một bản gộp thừa nối lại
    ba revision mà hai trong số đó **đã có con** (thành hai chỗ rẽ). Cả hai đều không đụng
    tới lược đồ nên không bài kiểm nội dung nào thấy.

    Nếu về sau có hai nhánh tách thật và cần một mối nối thật, bài này đỏ — và đó đúng là
    lúc cần một người quyết định, không phải lúc lặng lẽ thêm một mối nối nữa.
    """
    from collections import defaultdict

    from alembic.script import ScriptDirectory

    script = ScriptDirectory.from_config(_config())

    heads = script.get_heads()
    assert len(heads) == 1, f"chuỗi migration tách thành {len(heads)} head: {heads}"

    children: dict[str, list[str]] = defaultdict(list)
    merges: list[str] = []
    for revision in script.walk_revisions():
        parents = revision.down_revision
        if isinstance(parents, tuple):
            merges.append(revision.revision)
            for parent in parents:
                children[parent].append(revision.revision)
        elif parents:
            children[parents].append(revision.revision)

    assert not merges, f"có mối nối trong chuỗi migration: {merges}"
    forks = {parent: kids for parent, kids in children.items() if len(kids) > 1}
    assert not forks, f"có chỗ rẽ trong chuỗi migration: {forks}"
