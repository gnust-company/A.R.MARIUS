"""Health + meta endpoints."""

from __future__ import annotations

from fastapi import APIRouter

from armarius import __version__
from armarius.presentation.deps import ContainerDep
from armarius.presentation.schemas import MetaOut
from armarius.shared.config import settings

router = APIRouter(tags=["meta"])


@router.get("/healthz")
async def healthz() -> dict:
    return {"status": "ok", "service": "armarius", "version": __version__}


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
