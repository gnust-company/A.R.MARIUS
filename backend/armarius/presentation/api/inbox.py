"""Patron inbox endpoints (spec 001 §11, contracts/mat-nguoi-dung.md §5).

Replaces the browser-side filtering the Inbox page does today with a real surface. Every
route is scoped to the **calling** patron: there is deliberately no way to read or
resolve someone else's item, and an item that is not yours reads as *not found* rather
than *forbidden* so its existence stays hidden (Constitution I).

Live updates arrive on the patron event channel, not by polling (Constitution IV) — see
``GET /v1/inbox/events`` in the events router.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter

from armarius.domain.entities.inbox_item import InboxItemStatus
from armarius.presentation.api.auth import CurrentUser
from armarius.presentation.deps import ContainerDep
from armarius.presentation.schemas import InboxItemOut

router = APIRouter(prefix="/v1", tags=["inbox"])


@router.get("/inbox", response_model=list[InboxItemOut])
async def list_inbox(
    container: ContainerDep,
    user: CurrentUser,
    status: str = "pending",
    project_id: UUID | None = None,
) -> list[InboxItemOut]:
    """Items addressed to the caller. ``status=all`` returns both pending and resolved."""
    wanted = None if status == "all" else _parse_status(status)
    items = await container.inbox.list_for(
        str(user.id), status=wanted, project_id=project_id
    )
    return [InboxItemOut.model_validate(i) for i in items]


@router.post("/inbox/{item_id}/resolve", response_model=InboxItemOut)
async def resolve_inbox_item(
    item_id: UUID, container: ContainerDep, user: CurrentUser
) -> InboxItemOut:
    """Mark an item handled. Usually called implicitly by the decision itself; exposed so
    a patron can clear an item that stopped mattering.

    Routed through the recovery ladder rather than straight at the inbox, because for a
    stalled-task escalation this *is* the way down from Mức 3: the sweep lets go of a task
    once the letter is written, so handing the letter back is what puts it under the net
    again. Every other kind of item just resolves.
    """
    item = await container.recovery.patron_answered(
        item_id, recipient_user_id=str(user.id)
    )
    return InboxItemOut.model_validate(item)


def _parse_status(value: str) -> InboxItemStatus:
    try:
        return InboxItemStatus(value)
    except ValueError as exc:
        raise ValueError(f"unknown inbox status '{value}'") from exc
