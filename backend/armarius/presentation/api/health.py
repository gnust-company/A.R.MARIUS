"""Health + meta endpoints."""

from __future__ import annotations

from fastapi import APIRouter
from sqlalchemy import text

from armarius import __version__
from armarius.infrastructure.database.engine import get_engine
from armarius.presentation.deps import ContainerDep
from armarius.presentation.schemas import MetaOut
from armarius.shared.config import settings

router = APIRouter(tags=["meta"])


@router.get("/healthz")
async def healthz() -> dict:
    return {"status": "ok", "service": "armarius", "version": __version__}


async def _db_up() -> bool:
    try:
        async with get_engine().connect() as conn:
            await conn.execute(text("SELECT 1"))
        return True
    except Exception:
        return False


@router.get("/health")
async def health(container: ContainerDep) -> dict:
    db_up = await _db_up()
    minio_up = await container.artifact_store.healthy()
    return {
        "status": "ok" if (db_up and minio_up) else "degraded",
        "db": "up" if db_up else "down",
        "minio": "up" if minio_up else "down",
    }


@router.get("/v1/meta", response_model=MetaOut)
async def meta(container: ContainerDep) -> MetaOut:
    return MetaOut(
        version=__version__,
        public_base_url=settings.public_api_url,
        adapters=container.registry.types(),
    )


@router.get("/v1/adapters")
async def list_adapters(container: ContainerDep) -> dict:
    return {"adapters": container.registry.types()}
