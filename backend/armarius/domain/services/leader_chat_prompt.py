"""Leader-chat prompt builder — the text handed to the Leader for a project-level chat (#82).

Deliberately NOT the generic task-wake prompt (``build_wake_prompt``): that one tells the
agent to "update the task, publish an artifact, move to review/done" — meaningless for a
1-1 project conversation, which is why the project-level chat needs its own framing.

This is the project door's packet, so it carries the same four-part core every wake owes
(FR-044): the Leader's role here, the approved brief, why it is awake, and who else holds a
seat. What changes per call type is the extra below the core (FR-044a) — the snag list of a
cadence sweep, the dossier behind an escalation — and a patron simply writing has no extra
at all, which is why none is forced.

Here the Leader is framed as the project's lead in an ongoing chat with the patron about
the *whole* project. It answers/advises directly (its reply streams straight back, like
Open WebUI — we never ask the agent to call an API to deliver its answer). When the patron
asks it to create work, it uses its create-task tool; whether that becomes a live task or a
draft awaiting approval is governed by the **approved plan** (spec 001 FR-027) — the items
the patron signed off are listed in the prompt, and work outside them is a scope change.
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from armarius.domain.services.wake_prompt import NONE_MARKER, ProjectBrief


@dataclass(frozen=True)
class ChatDirectoryEntry:
    marius_id: UUID
    name: str
    role: str  # the worker's PROJECT role title (resolved via SeatGrant.role_id → Role)
    liveness: str
    role_description: str = ""  # what that project role does (optional)


@dataclass(frozen=True)
class PlanScopeEntry:
    """One item of the approved plan — what the Leader is allowed to start on its own."""

    item_id: UUID
    title: str


@dataclass(frozen=True)
class ChatTurn:
    role: str  # "patron" | "leader" | "system"
    text: str


@dataclass(frozen=True)
class LeaderChatContext:
    leader_name: str
    project_id: UUID
    project_name: str
    workspace_name: str
    # The brief the patron approved (FR-009) — the same five parts, from the same version,
    # that every worker on this project is woken with. `None` until one is approved.
    project_brief: ProjectBrief | None
    # The patron's own commission text off the project row. Raw material for the brief, not
    # a substitute for it: shown only while there is no approved version, and always
    # labelled as unapproved. It is the patron's writing, so it stays in their words.
    commission: str
    directory: list[ChatDirectoryEntry]
    recent_turns: list[ChatTurn]
    plan_items: list[PlanScopeEntry]
    # The Leader's own project role description (its leader Role), shown in the header so the
    # Leader knows the duties attached to its seat. Empty when the leader role has none.
    leader_role_description: str = ""
    # Part 3 of the four-part core (FR-044): why this turn is happening at all. Empty when
    # the patron simply wrote something — then the reason is their message, sitting right
    # there in the conversation, and repeating it as a heading would be noise.
    wake_reason: str = ""
    # What this particular call type owes on top of the core (FR-044a): the snag list of a
    # cadence sweep, the dossier behind an escalation. Agent-only, so English.
    wake_detail: str = ""


def _value(text: str | None) -> str:
    """An empty part reads as absent, never as a gap the agent has to interpret."""
    return text.strip() if text and text.strip() else NONE_MARKER


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
    lines.append("")

    lines.append("## Project context")
    if ctx.project_brief is not None:
        # Same five parts, same wording as the worker packet. The Leader and the worker
        # judging each other's work off two different briefs is how a project drifts.
        lines.append(
            "The brief the patron approved for this project. It is what you and your "
            "workers both answer to — judge proposals and finished work against it."
        )
        lines.append(f"- Objective: {_value(ctx.project_brief.objective)}")
        lines.append(f"- Background: {_value(ctx.project_brief.background)}")
        lines.append(f"- Constraints: {_value(ctx.project_brief.constraints)}")
        lines.append(f"- Scope: {_value(ctx.project_brief.scope)}")
        lines.append(f"- Principles: {_value(ctx.project_brief.principles)}")
    else:
        lines.append(
            "There is **no approved brief** for this project yet. Writing one with the "
            "patron is your job here; until they approve it, nothing below is settled."
        )
        if ctx.commission.strip():
            lines.append(
                f"- What the patron wrote when they opened the project: "
                f"{ctx.commission.strip()}"
            )
    lines.append("")

    # Part 3 of the core (FR-044), before the team so the Leader knows what it is here for
    # while it reads who is available to help.
    if ctx.wake_reason:
        lines.append("## Why you were woken")
        lines.append(f"- {ctx.wake_reason.strip()}")
        lines.append("")
        if ctx.wake_detail.strip():
            lines.append(ctx.wake_detail.strip())
            lines.append("")

    # Part 4 of the core. Always rendered, empty or not (FR-045): a Leader that cannot tell
    # "nobody has been seated yet" from "the roster failed to load" invents a team.
    lines.append("## Your team (workers you can assign)")
    if ctx.directory:
        for d in ctx.directory:
            role = d.role or "—"
            lines.append(f"- {d.name} ({role}) [{d.liveness}] — marius_id: {d.marius_id}")
            if d.role_description:
                lines.append(f"    role: {d.role_description.strip()}")
    else:
        lines.append(f"- {NONE_MARKER} — nobody else holds a seat on this project yet.")
    lines.append("")

    if ctx.recent_turns:
        lines.append("## Conversation so far")
        for t in ctx.recent_turns:
            # A system line is neither the patron speaking nor the Leader: attributing it
            # to "You" fed the Leader its own wake notices back as things it had said.
            who = {"patron": "Patron", "leader": "You"}.get(t.role, "System")
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
        '`{"title": ..., "description": ..., "assignee_marius_id": <optional>, '
        '"plan_item_id": <optional>}`. '
        "Break the request down and fill in a clear title + description and, when obvious, "
        "the best worker to assign from your team above. The description is mandatory "
        "before anyone can be assigned — a title alone is refused."
    )
    if ctx.plan_items:
        lines.append(
            "- The patron approved these plan items. Work that belongs to one of them is "
            "**yours to start**: pass its `plan_item_id` and the task goes live and is "
            "assigned immediately, no approval round."
        )
        for item in ctx.plan_items:
            lines.append(f"  - `{item.item_id}` — {item.title}")
        lines.append(
            "- Work that fits **none** of them widens the project's scope: create it "
            "without a `plan_item_id`. It stays a draft and the patron is asked to decide. "
            "Tell them you have proposed it and it is awaiting their approval."
        )
    else:
        lines.append(
            "- No plan item has been approved for this project yet, so every task you "
            "create stays a **draft** awaiting the patron's approval. Say so when you "
            "propose one."
        )
    lines.append(
        "- Do NOT create a task for a question or a discussion — only when the patron "
        "clearly wants work started."
    )
    return "\n".join(lines)
