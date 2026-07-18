"""Wake prompt builder — assembles the text handed to a Marius on wake.

Pure function over plain value objects so it stays unit-testable. The prompt always
carries the Agent Directory (§3.1) so the agent knows who it can talk to, plus the
task brief, the new thread messages since it last slept, and its own next_action.
"""

from __future__ import annotations

from dataclasses import dataclass

from armarius.domain.entities.run import WakeSource
from armarius.domain.services.agent_prompt import agent_prompt_footer


@dataclass(frozen=True)
class DirectoryEntry:
    name: str
    role: str  # the teammate's PROJECT role title (resolved via SeatGrant.role_key → Role)
    skills: list[str]
    liveness: str
    role_description: str = ""  # what that project role does (optional)


@dataclass(frozen=True)
class ThreadMessage:
    author: str
    body: str


@dataclass(frozen=True)
class WakeContext:
    marius_name: str
    task_title: str
    task_status: str
    task_description: str | None
    next_action: str | None
    directory: list[DirectoryEntry]
    new_messages: list[ThreadMessage]
    source: WakeSource
    reason: str | None = None
    # The woken agent's OWN role in THIS project (title + description), resolved via its
    # SeatGrant.role_key → Role. Empty when the agent holds no seat in the project.
    self_role: str = ""
    self_role_description: str = ""
    # Where this wake comes from (#15): a multi-workspace agent holds one token per
    # workspace, so every prompt names its workspace/project and the exact credential
    # file to read — the agent must never guess among several files.
    workspace_name: str = ""
    project_name: str = ""
    credential_file: str | None = None


def build_wake_prompt(ctx: WakeContext) -> str:
    lines: list[str] = []
    if ctx.self_role:
        lines.append(
            f"You are {ctx.marius_name}, the {ctx.self_role} on this project inside Armarius."
        )
        if ctx.self_role_description:
            lines.append(ctx.self_role_description.strip())
    else:
        lines.append(f"You are {ctx.marius_name}, an agent collaborating inside Armarius.")
    lines.append("")

    if ctx.workspace_name or ctx.project_name:
        lines.append("## Where you are")
        lines.append(
            f"- Workspace: {ctx.workspace_name or 'unknown'}"
            f" · Project: {ctx.project_name or 'unknown'}"
        )
        lines.append("")

    lines.append(f"## Task: {ctx.task_title}  [{ctx.task_status}]")
    if ctx.task_description:
        lines.append(ctx.task_description.strip())
    lines.append("")

    lines.append("## Why you were woken")
    woke = f"- source: {ctx.source}"
    if ctx.reason:
        woke += f" — {ctx.reason}"
    lines.append(woke)
    lines.append("")

    if ctx.directory:
        lines.append("## Your teammates on this project (who you can @mention)")
        for d in ctx.directory:
            skills = ", ".join(d.skills) if d.skills else "—"
            role = d.role or "—"
            lines.append(f"- @{d.name} ({role}) [{d.liveness}] skills: {skills}")
            if d.role_description:
                lines.append(f"    role: {d.role_description.strip()}")
        lines.append("")

    if ctx.new_messages:
        lines.append("## New messages since you last worked")
        for m in ctx.new_messages:
            lines.append(f"- {m.author}: {m.body}")
        lines.append("")

    if ctx.next_action:
        lines.append("## Your recorded next action")
        lines.append(ctx.next_action.strip())
        lines.append("")

    lines.append("## How to act")
    lines.append(
        "- Use your Armarius tools to update the task, post comments (@mention to ask "
        "others), and publish artifacts."
    )
    lines.append(
        "- A task can only be moved to review/done once you have published an artifact "
        "to the shared store."
    )
    lines.append(
        "- Before you stop, record a durable `next_action` via update_task so the work "
        "can resume even if your session is lost."
    )
    # Every system→agent message ends with the SAME token-location footer so even a weak
    # model always knows where its token lives — unconditional, identical to the invite,
    # skill-install and onboarding prompts (#80). No task-wake ever goes out without it.
    return "\n".join(lines) + agent_prompt_footer(ctx.credential_file)
