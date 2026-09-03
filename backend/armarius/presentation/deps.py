"""FastAPI dependency wiring — pulls singletons off app.state and resolves agent auth."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Header, Request

from armarius.domain.entities.marius import Marius
from armarius.infrastructure.daemon.run_auth import RunCaller
from armarius.infrastructure.persistence.unit_of_work import make_uow
from armarius.presentation.container import Container
from armarius.shared.errors import NotFound, Unauthorized


def get_container(request: Request) -> Container:
    return request.app.state.container  # type: ignore[no-any-return]


ContainerDep = Annotated[Container, Depends(get_container)]


# A run that resolved to nothing is a real answer and has to be remembered as one, so the
# "not looked up yet" case needs a marker of its own rather than borrowing None.
_NOT_LOOKED_UP = object()


def _bearer(authorization: str | None) -> str:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise Unauthorized("missing_bearer_token")
    return authorization.split(" ", 1)[1].strip()


async def resolve_run(
    request: Request,
    container: Container,
    authorization: str | None,
) -> RunCaller | None:
    """The run behind this request, looked up at most once however often it is asked for.

    Two things ask: the scope guard on the router, which needs the run *before* deciding
    whether the route is even in bounds, and `get_current_run` below. FastAPI caches a
    dependency's result per request, but the guard cannot go through the dependency: it must
    stay silent on a token that opens nothing and let the route's own door give that answer,
    with the code that names the real cause. So the answer is memoised on the request
    instead, and both askers share the one lookup.
    """
    cached = getattr(request.state, "run_caller", _NOT_LOOKED_UP)
    if cached is not _NOT_LOOKED_UP:
        return cached  # type: ignore[no-any-return]
    caller = await container.run_auth.authenticate(_bearer(authorization))
    request.state.run_caller = caller
    return caller


async def get_current_run(
    request: Request,
    container: ContainerDep,
    authorization: Annotated[str | None, Header()] = None,
) -> RunCaller:
    """Resolve the calling run from the token its agent was started with (FR-014g).

    **Every** `/agent/*` route comes through here, which is why changing the credential was
    a change to one function rather than to twenty-two. The two onboarding routes were the
    last exception, and they stopped being one when the team-building interview became a run
    of its own (FR-040c): there is now no door left that a long-lived per-agent token could
    open, and no such token either (FR-014a).

    **Nothing resolved reads as 404, not 401 and never 403.** The token *is* the run: a
    string that opens no run names no run, and Constitution I says a thing that is not
    yours must read exactly like a thing that is not there. It also collapses the two ways
    of holding a useless token — never valid, and valid until the run closed — into one
    answer, so nobody can use the door to confirm that a string they found once worked.
    The refusal carries its own code, `run_not_found`, which is what lets the daemon tell
    *my credential died* from *no such task* and treat the first as needing a person
    (FR-014f) without the status line having to carry that distinction.
    """
    caller = await resolve_run(request, container, authorization)
    if caller is None:
        raise NotFound("run_not_found")
    return caller


CurrentRun = Annotated[RunCaller, Depends(get_current_run)]


async def get_current_marius(run: CurrentRun) -> Marius:
    """The agent the calling run speaks for.

    Derived from the run rather than looked up on its own, so an agent identity can only
    ever exist inside a live run. Routes that need nothing but *who is this* keep taking
    `CurrentMarius` and are unaffected by where it now comes from.
    """
    async with make_uow() as uow:
        marius = await uow.mariuses.get(run.marius_id)
    if marius is None:
        # A run points at an agent that has since been deleted. Same answer as a run that
        # was never there: there is no caller here to talk to.
        raise NotFound("run_not_found")
    return marius


CurrentMarius = Annotated[Marius, Depends(get_current_marius)]
