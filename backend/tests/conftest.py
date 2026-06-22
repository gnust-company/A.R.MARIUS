from __future__ import annotations

from collections.abc import AsyncIterator, Callable

import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from armarius.infrastructure.database.models import Base
from armarius.infrastructure.persistence.unit_of_work import SqlAlchemyUnitOfWork


@pytest_asyncio.fixture
async def uow_factory(tmp_path) -> AsyncIterator[Callable[[], SqlAlchemyUnitOfWork]]:
    db_path = tmp_path / "test.db"
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{db_path}", connect_args={"timeout": 30}
    )
    async with engine.begin() as conn:
        await conn.exec_driver_sql("PRAGMA journal_mode=WAL;")
        await conn.run_sync(Base.metadata.create_all)
    sessionmaker = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

    def factory() -> SqlAlchemyUnitOfWork:
        return SqlAlchemyUnitOfWork(sessionmaker)

    yield factory
    await engine.dispose()
