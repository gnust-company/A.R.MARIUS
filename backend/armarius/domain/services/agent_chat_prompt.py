"""The packet for one turn of the patron's direct conversation with an agent (FR-007p).

Pure function over plain values, like every other prompt builder here.

This is the smallest packet an agent is ever handed, and on purpose. A task packet carries a
project brief, a team and a thread because the agent is about to work inside them; here there
is nothing to work inside. What the agent needs is who it is — its instructions, in the one
shape every packet renders them (``append_instructions``) — the conversation so far, and the
message it is answering.

The conversation travels inside the message rather than in a session kept on the far side.
A turn with no task keeps no session of its own where it runs, which is the same answer the
project chat gives for the same reason.

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


def build_agent_chat_prompt(ctx: AgentChatContext) -> str:
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
    if ctx.history:
        for turn in ctx.history:
            who = {"patron": "Patron", "agent": "You"}.get(turn.role, "System")
            lines.append(f"- {who}: {turn.text}")
    else:
        lines.append(f"- {NONE_MARKER} — this is the first message.")
    lines.append("")

    lines.append("## Their message")
    lines.append(ctx.message.strip())
    return "\n".join(lines)
