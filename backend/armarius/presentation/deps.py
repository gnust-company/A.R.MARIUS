"""FastAPI dependency wiring — pulls singletons off app.state and resolves agent auth."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Header, Request

from armarius.domain.entities.marius import Marius
from armarius.infrastructure.persistence.unit_of_work import make_uow
from armarius.presentation.container import Container
from armarius.shared.errors import Unauthorized


def get_container(request: Request) -> Container:
    return request.app.state.container  # type: ignore[no-any-return]


ContainerDep = Annotated[Container, Depends(get_container)]


async def get_current_marius(
    authorization: Annotated[str | None, Header()] = None,
) -> Marius:
    """Resolve the calling agent from its bearer token (agent-facing API)."""
    if not authorization or not authorization.lower().startswith("bearer "):
        raise Unauthorized("missing_bearer_token")
    token = authorization.split(" ", 1)[1].strip()
    async with make_uow() as uow:
        marius = await uow.mariuses.get_by_token(token)
    if marius is None:
        raise Unauthorized("invalid_agent_token")
    return marius


CurrentMarius = Annotated[Marius, Depends(get_current_marius)]
