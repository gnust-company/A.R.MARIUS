"""What an agent said in one run, read back out of the record.

Both chats rebuild a reply this way when the turn was taken somewhere this process did not
watch: the project chat with its Leader, and the patron's direct conversation with an agent.
One reader, so the two cannot disagree about what "the reply" is.
"""

from __future__ import annotations

from uuid import UUID

from armarius.application.ports.unit_of_work import UnitOfWork

# What an agent produced, as the machine writes it down. A turn taken elsewhere leaves its
# words here and nowhere else — the same name the in-process road coalesces its deltas into,
# so one reader answers for both roads.
SAID = "assistant.message"


async def said_in(uow: UnitOfWork, run_id: UUID) -> str:
    """Everything the agent said in one run, in the order it said it.

    An event that carries only the opening of something long is followed to the rest
    (FR-049). Rebuilding a reply out of the openings would put a silently truncated answer in
    the agent's mouth, which is worse than a missing one: nothing on the screen would say it
    had been cut.
    """
    parts: list[str] = []
    for event in await uow.run_events.list_by_run(run_id, types=[SAID]):
        said = str(event.payload.get("text") or "")
        if event.full_field:
            whole = await uow.run_events.full_text(run_id, event.seq)
            if whole is not None:
                said = whole[1]
        if said:
            parts.append(said)
    return "".join(parts).strip()
