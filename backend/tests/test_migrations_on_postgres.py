"""Chuỗi migration đi được **cả hai chiều trên Postgres**, không chỉ trên SQLite (T005b).

Bài `test_migrations.py` chạy chuỗi này trên SQLite và xanh. Trên Postgres thì `downgrade base`
chết ở `e9c2a4d7f0b3` với `relation "pk_seat_grants" already exists` — vì tên ràng buộc trên
Postgres là duy nhất trong **cả schema**, còn trên SQLite chỉ cần duy nhất trong **một bảng**. Nên
một migration dựng bảng tạm mang đúng tên ràng buộc của bảng thật chạy được ở dialect này và chết ở
dialect kia, và bộ kiểm không thấy gì.

**Bài này chỉ chạy khi được chỉ vào một Postgres**, qua `ARMARIUS_TEST_POSTGRES_URL` — dạng
`postgresql+psycopg://user:pass@host:port` (không kèm tên database: bài tự tạo một cái tạm và xoá
đi). Không có biến ấy thì nó bỏ qua, và tôi nói thẳng điều đó ra đây thay vì để con số *đã đạt* che
mất: hôm nay kho chưa có CI, nên thứ thật sự chạy bài này là một người gõ biến môi trường.
"""

from __future__ import annotations

import os
import uuid

import pytest
from alembic import command
from sqlalchemy import create_engine, inspect, text

from armarius.infrastructure.database.migrations import _config
from armarius.shared.config import settings

BASE = os.getenv("ARMARIUS_TEST_POSTGRES_URL", "").rstrip("/")

pytestmark = pytest.mark.skipif(
    not BASE, reason="đặt ARMARIUS_TEST_POSTGRES_URL để chạy bài này"
)


def test_the_chain_goes_down_to_base_and_back_up_on_postgres() -> None:
    name = f"mig_probe_{uuid.uuid4().hex[:10]}"
    admin = create_engine(BASE + "/postgres", isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        conn.execute(text(f'CREATE DATABASE "{name}"'))
    url = f"{BASE}/{name}"
    try:
        before = settings.database_url
        settings.database_url = url
        try:
            cfg = _config()
            command.upgrade(cfg, "head")
            # Chiều đi xuống là chiều hỏng, nên nó là chiều bài này sinh ra để giữ.
            command.downgrade(cfg, "base")
            command.upgrade(cfg, "head")
        finally:
            settings.database_url = before

        # Và vòng về phải trả lại đúng tên ràng buộc chuẩn — nếu không thì lần đi xuống sau
        # lại đụng đúng bức tường cũ.
        insp = inspect(create_engine(url))
        names = {c["name"] for c in insp.get_foreign_keys("seat_grants")}
        names.add(insp.get_pk_constraint("seat_grants")["name"])
        assert "pk_seat_grants" in names, names
        assert "fk_seat_grants_project_id" in names, names
    finally:
        with admin.connect() as conn:
            conn.execute(
                text(
                    "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                    "WHERE datname = :n"
                ),
                {"n": name},
            )
            conn.execute(text(f'DROP DATABASE IF EXISTS "{name}"'))
