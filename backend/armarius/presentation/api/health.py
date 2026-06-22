"""Health + meta endpoints."""

from __future__ import annotations

from fastapi import APIRouter

from armarius import __version__
from armarius.presentation.deps import ContainerDep

router = APIRouter(tags=["meta"])


@router.get("/healthz")
async def healthz() -> dict:
    return {"status": "ok", "service": "armarius", "version": __version__}


@router.get("/v1/adapters")
async def list_adapters(container: ContainerDep) -> dict:
    return {"adapters": container.registry.types()}
