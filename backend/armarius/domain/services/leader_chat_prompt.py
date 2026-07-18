"""Leader-chat prompt builder — the text handed to the Leader for a project-level chat (#82).

Deliberately NOT the generic task-wake prompt (``build_wake_prompt``): that one tells the
agent to "update the task, publish an artifact, move to review/done" — meaningless for a
1-1 project conversation and the reason the old Commission wake felt *bạc nhược* (feeble).

Here the Leader is framed as the project's lead in an ongoing chat with the patron about
the *whole* project. It answers/advises directly (its reply streams straight back, like
Open WebUI — we never ask the agent to call an API to deliver its answer). When the patron
asks it to create work, it uses its create-task tool; whether that becomes a draft awaiting
approval or a live task is governed by the project's YOLO mode, stated in the prompt.
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from armarius.domain.services.agent_prompt import agent_prompt_footer


@dataclass(frozen=True)
class ChatDirectoryEntry:
    marius_id: UUID
    name: str
    role: str  # the worker's PROJECT role title (resolved via SeatGrant.role_key → Role)
    liveness: str
    role_description: str = ""  # what that project role does (optional)


@dataclass(frozen=True)
class ChatTurn:
    role: str  # "patron" | "leader"
    text: str


@dataclass(frozen=True)
class LeaderChatContext:
    leader_name: str
    project_id: UUID
    project_name: str
    workspace_name: str
    project_context: str | None
    directory: list[ChatDirectoryEntry]
    recent_turns: list[ChatTurn]
    yolo_mode: bool
    # The Leader's own project role description (its leader Role), shown in the header so the
    # Leader knows the duties attached to its seat. Empty when the leader role has none.
    leader_role_description: str = ""
    credential_file: str | None = None


def build_leader_chat_prompt(ctx: LeaderChatContext) -> str:
    lines: list[str] = []
    lines.append(
        f"You are {ctx.leader_name}, the Leader of this project inside Armarius."
    )
    if ctx.leader_role_description:
        lines.append(ctx.leader_role_description.strip())
    lines.append(
        "This is the project's **Chat with Leader** — a 1-1 conversation with your patron "
        "about anything in the project (direction, status, planning, decisions)."
    )
    lines.append("")

    lines.append("## Where you are")
    lines.append(
        f"- Workspace: {ctx.workspace_name or 'unknown'}"
        f" · Project: {ctx.project_name or 'unknown'} (id: {ctx.project_id})"
    )
    if ctx.project_context:
        lines.append(f"- Project context: {ctx.project_context.strip()}")
    lines.append("")

    if ctx.directory:
        lines.append("## Your team (workers you can assign)")
        for d in ctx.directory:
            role = d.role or "—"
            lines.append(f"- {d.name} ({role}) [{d.liveness}] — marius_id: {d.marius_id}")
            if d.role_description:
                lines.append(f"    role: {d.role_description.strip()}")
        lines.append("")

    if ctx.recent_turns:
        lines.append("## Conversation so far")
        for t in ctx.recent_turns:
            who = "Patron" if t.role == "patron" else "You"
            lines.append(f"- {who}: {t.text}")
        lines.append("")

    lines.append("## How to act")
    lines.append(
        "- Reply directly and concisely to the patron's latest message. Your reply is "
        "shown to the patron as it streams — just answer, do NOT call any API to deliver it."
    )
    lines.append(
        "- Use your read tools freely to ground your answer in the real project state "
        "(tasks, roster, artifacts) before you respond."
    )
    lines.append("### When the patron asks you to create work")
    lines.append(
        "- Create the task with your create-task tool: "
        f"`POST /agent/projects/{ctx.project_id}/tasks` with JSON "
        '`{"title": ..., "description": ..., "assignee_marius_id": <optional>}`. '
        "Break the request down and fill in a clear title + description and, when obvious, "
        "the best worker to assign from your team above."
    )
    if ctx.yolo_mode:
        lines.append(
            "- YOLO mode is **ON** for this project: the task is created live and assigned "
            "immediately. Only create tasks the patron actually asked for."
        )
    else:
        lines.append(
            "- YOLO mode is **OFF**: the task is created as a **draft** and waits for the "
            "patron to approve it before any worker is woken. Tell the patron you've "
            "proposed it and it's awaiting their approval."
        )
    lines.append(
        "- Do NOT create a task for a question or a discussion — only when the patron "
        "clearly wants work started."
    )
    return "\n".join(lines) + agent_prompt_footer(ctx.credential_file)
