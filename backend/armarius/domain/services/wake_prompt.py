"""Wake prompt builder — assembles the text handed to a Marius on wake.

Pure function over plain value objects so it stays unit-testable.

Spec 001 FR-044 fixes the shape: **eight** parts, always, in this order —

  1. the agent's role on this project
  2. the approved project brief
  3. the task, its description and its status
  4. why it was woken, in a sentence a person can read (FR-046)
  5. the teammates it can talk to, with their liveness
  6. what was said while it was asleep
  7. the next action waiting to be picked up
  8. where to put the work and how to report status

FR-045 adds the rule that makes the shape worth having: a part with nothing in it says so
(``NONE_MARKER``) instead of disappearing. A section that is simply absent is ambiguous —
the agent cannot tell "nobody has said anything" from "that section failed to render", so
it fills the gap with a guess. An explicitly empty section is a fact it can act on.
"""

from __future__ import annotations

from dataclasses import dataclass

from armarius.domain.entities.run import WakeSource
from armarius.domain.services.agent_prompt import agent_prompt_footer

# What an empty part reads as. One constant so no caller invents its own wording, and so a
# test can count the empty parts of a packet.
NONE_MARKER = "(none)"


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
class ProjectBrief:
    """The approved project context, part 2 of the packet (FR-009).

    The gap this closes: the Leader received the objective in its chat prompt while the
    worker actually doing the job never did — so the worker judged its own output against
    nothing but the task title.
    """

    objective: str = ""
    background: str = ""
    constraints: str = ""
    scope: str = ""
    principles: str = ""


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
    # The approved brief (FR-009). `None` when the project has none approved yet — which
    # is itself worth saying out loud, so the agent knows nobody has set direction.
    project_brief: ProjectBrief | None = None
    # Where this wake comes from (#15): a multi-workspace agent holds one token per
    # workspace, so every prompt names its workspace/project and the exact credential
    # file to read — the agent must never guess among several files.
    workspace_name: str = ""
    project_name: str = ""
    credential_file: str | None = None


def _value(text: str | None) -> str:
    return text.strip() if text and text.strip() else NONE_MARKER


def build_wake_prompt(ctx: WakeContext) -> str:
    lines: list[str] = []

    # ── 1. the agent's role on this project ────────────────────────────────────
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

    # ── 2. the approved brief ──────────────────────────────────────────────────
    brief = ctx.project_brief or ProjectBrief()
    lines.append("## Project context")
    lines.append(
        "The brief the patron approved for this project. Judge your work against it, "
        "not against the task title alone."
    )
    lines.append(f"- Objective: {_value(brief.objective)}")
    lines.append(f"- Background: {_value(brief.background)}")
    lines.append(f"- Constraints: {_value(brief.constraints)}")
    lines.append(f"- Scope: {_value(brief.scope)}")
    lines.append(f"- Principles: {_value(brief.principles)}")
    lines.append("")

    # ── 3. the task ────────────────────────────────────────────────────────────
    lines.append(f"## Task: {ctx.task_title}  [{ctx.task_status}]")
    lines.append(_value(ctx.task_description))
    lines.append("")

    # ── 4. why now (FR-046) ────────────────────────────────────────────────────
    lines.append("## Why you were woken")
    woke = f"- source: {ctx.source}"
    if ctx.reason:
        woke += f" — {ctx.reason.strip()}"
    lines.append(woke)
    lines.append("")

    # ── 5. who else is here ────────────────────────────────────────────────────
    lines.append("## Your teammates on this project (who you can @mention)")
    if ctx.directory:
        for d in ctx.directory:
            skills = ", ".join(d.skills) if d.skills else "—"
            role = d.role or "—"
            lines.append(f"- @{d.name} ({role}) [{d.liveness}] skills: {skills}")
            if d.role_description:
                lines.append(f"    role: {d.role_description.strip()}")
    else:
        lines.append(f"- {NONE_MARKER} — you are the only seat holder on this project.")
    lines.append("")

    # ── 6. what happened while it slept ────────────────────────────────────────
    lines.append("## New messages since you last worked")
    if ctx.new_messages:
        for m in ctx.new_messages:
            lines.append(f"- {m.author}: {m.body}")
    else:
        lines.append(f"- {NONE_MARKER}")
    lines.append("")

    # ── 7. the work waiting to be picked up ────────────────────────────────────
    lines.append("## Your recorded next action")
    lines.append(_value(ctx.next_action))
    lines.append("")

    # ── 8. how to hand the work back ───────────────────────────────────────────
    # Its own part, not a bullet buried in general advice: this is what the agent looks up
    # when it is finished, and it competes with nothing when it has a heading of its own.
    lines.append("## Where to put your work and how to report status")
    lines.append(
        "- Publish every deliverable as an **artifact** to the shared store with your "
        "publish-artifact tool. Work that is not an artifact does not exist to anyone else."
    )
    lines.append(
        "- Report status with update_task. A task can only reach review or done once an "
        "artifact has been published."
    )
    lines.append(
        "- Before you stop, record a durable `next_action` — either who the ball is now "
        "with, or exactly what is left half-done — so the work resumes even if your "
        "session is lost."
    )
    lines.append("")

    lines.append("## How to act")
    lines.append(
        "- Use your Armarius tools to update the task and post comments (@mention to ask "
        "others)."
    )
    # Every system→agent message ends with the SAME token-location footer so even a weak
    # model always knows where its token lives — unconditional, identical to the invite,
    # skill-install and onboarding prompts (#80). No task-wake ever goes out without it.
    return "\n".join(lines) + agent_prompt_footer(ctx.credential_file)
