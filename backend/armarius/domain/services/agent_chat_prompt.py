"""The packet for one turn of the patron's direct conversation with an agent (FR-007p).

Pure function over plain values, like every other prompt builder here.

This is the smallest packet an agent is ever handed, and on purpose. A task packet carries a
project brief, a team and a thread because the agent is about to work inside them; here there
is nothing to work inside. What the agent needs is who it is — its instructions, in the one
shape every packet renders them (``append_instructions``) — the conversation so far, and the
message it is answering.

Two forms of the same packet (FR-040c). The conversation lives in the agent's own session,
which the machine keeps between turns, so the ordinary turn says only what is new —
`carrying_on`. When that session is not there to carry on (the first message, a session past its
keeping, one the CLI refused), the recent turns are written back in instead, so losing a
session never costs the patron the thread.

English throughout: it is the agent's copy (Constitution VII).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from armarius.domain.services.leader_chat_prompt import ChatTurn
from armarius.domain.services.wake_prompt import NONE_MARKER, append_instructions

# How much of the conversation rides each turn. Enough to hold a thread together; a longer
# history belongs to the transcript on screen, not to every packet.
TURN_TAIL = 20


@dataclass(frozen=True)
class AgentChatContext:
    agent_name: str
    workspace_name: str
    message: str
    instructions: str = ""
    system_instructions: str = ""
    history: list[ChatTurn] = field(default_factory=list)


def build_agent_chat_prompt(ctx: AgentChatContext, *, carrying_on: bool = False) -> str:
    lines: list[str] = [
        f"You are {ctx.agent_name}, an agent in the {ctx.workspace_name or 'unnamed'} "
        "workspace inside Armarius.",
        "",
    ]
    append_instructions(
        lines, instructions=ctx.instructions, system_instructions=ctx.system_instructions
    )

    lines.append("## This conversation")
    lines.append(
        "Your patron is talking to you directly. It is not a task: no project, board or "
        "deliverable is attached to it, and nothing said here creates work — work reaches you "
        "through projects. Answer the way you would answer a colleague, in plain text and in "
        "the language they wrote in. Your reply is shown to them as you write it; do not call "
        "anything to deliver it."
    )
    lines.append("")

    # Always rendered (FR-045): an agent that cannot tell "this is the first message" from
    # "the history failed to load" answers as though it had forgotten.
    lines.append("## Conversation so far")
    if carrying_on:
        # Said, not left out: a section that simply vanishes cannot be told apart from one that
        # failed to render (FR-045), and an agent that thinks its history was lost answers as
        # though it had been.
        lines.append(
            "- The earlier turns are in this conversation's own history; they are not repeated "
            "here."
        )
    elif ctx.history:
        for turn in ctx.history:
            who = {"patron": "Patron", "agent": "You"}.get(turn.role, "System")
            lines.append(f"- {who}: {turn.text}")
    else:
        lines.append(f"- {NONE_MARKER} — this is the first message.")
    lines.append("")

    lines.append("## Their message")
    lines.append(ctx.message.strip())
    return "\n".join(lines)
