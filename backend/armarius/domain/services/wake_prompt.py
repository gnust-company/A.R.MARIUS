"""Wake prompt builder — assembles the text handed to a Marius on wake.

Pure function over plain value objects so it stays unit-testable.

Spec 001 FR-044 fixes a **four-part core** no wake is exempt from —

  1. the agent's role on this project
  2. the approved project brief (FR-009)
  3. why it was woken, in a sentence a person can read (FR-046)
  4. the teammates it can talk to, with their liveness

Those four settle the three things any agent must know before it does anything at all: who
it is here, where the project is going, and why it is awake right now. Miss one and the
agent guesses, and a guessing agent is a wrong agent.

FR-044a supplies the rest **per call type** rather than one shape for everyone. This module
builds the packets that leave by the task door, where the extras are the task and the
thread on it; a worker additionally gets its recorded next action and how to hand work
back, and the Leader does not — it was pulled onto this task to judge or decide, not to
hand anything in. Five of the eight parts of the old one-shape-fits-all packet meant
nothing to the Leader, and a box filled in for the sake of filling it in is worse than a
box that was never there.

FR-045 governs what happens *inside* the parts a packet does carry: a part with nothing in
it says so (``NONE_MARKER``) instead of disappearing. A section that is simply absent is
ambiguous — the agent cannot tell "nobody has said anything" from "that section failed to
render", so it fills the gap with a guess. An explicitly empty section is a fact it can act
on. The rule bans silence in the parts a call type has; it does not hand a call type parts
that are not its own.

Everything written here is English: it is the agent's copy, and an agent has no interface
language to choose (Constitution VII). What the *patron* reads about the same wake is
rendered separately from the cause's code and parameters — see `wake_reason`.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum

from armarius.domain.entities.run import WakeSource
from armarius.domain.services.agent_prompt import agent_prompt_footer
from armarius.domain.services.orchestration_cadence import Snag

# What an empty part reads as. One constant so no caller invents its own wording, and so a
# test can count the empty parts of a packet.
NONE_MARKER = "(none)"


class WakeAudience(StrEnum):
    """Who the packet is addressed to — the two hats the task door can wake (FR-048a).

    Read off the work rather than off the agent record, exactly as the cause guard reads
    it: whoever holds the task is its worker, whoever holds the leader seat is its Leader.
    An agent wearing both hats on the same task is woken as the worker — it is the one
    doing the job, and the job is what the extras are for.
    """

    WORKER = "worker"
    LEADER = "leader"


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
    """The approved project context, part 2 of the core (FR-009).

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
    # Which set of extras rides along (FR-044a). Defaults to the worker packet because the
    # task door was built for it; the Leader is the case that has to be asked for.
    audience: WakeAudience = WakeAudience.WORKER
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


# ── the four-part core (FR-044) ──────────────────────────────────────────────────


def _core(ctx: WakeContext, lines: list[str]) -> None:
    """The four parts every wake carries, in the order the requirement lists them."""

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

    # ── 3. why now (FR-046) ────────────────────────────────────────────────────
    lines.append("## Why you were woken")
    woke = f"- source: {ctx.source}"
    if ctx.reason:
        woke += f" — {ctx.reason.strip()}"
    lines.append(woke)
    lines.append("")

    # ── 4. who else is here ────────────────────────────────────────────────────
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


# ── the task door's extras (FR-044a) ─────────────────────────────────────────────


def _task_extras(ctx: WakeContext, lines: list[str]) -> None:
    """What a wake about one task adds to the core.

    The task and its thread go to both hats: the Leader cannot judge work it has not been
    shown, and the conversation on the task is where it was asked to look in the first
    place. The two parts below them are the worker's alone.
    """
    lines.append(f"## Task: {ctx.task_title}  [{ctx.task_status}]")
    lines.append(_value(ctx.task_description))
    lines.append("")

    lines.append("## New messages since you last worked")
    if ctx.new_messages:
        for m in ctx.new_messages:
            lines.append(f"- {m.author}: {m.body}")
    else:
        lines.append(f"- {NONE_MARKER}")
    lines.append("")

    if ctx.audience is WakeAudience.LEADER:
        lines.append("## How to act")
        lines.append(
            "- You are not the one doing this task. Read it, then judge, decide or answer."
        )
        lines.append(
            "- Use your Armarius tools: post a comment (@mention to reach someone), sign "
            "the work off, or send it back with what has to change."
        )
        return

    lines.append("## Your recorded next action")
    lines.append(_value(ctx.next_action))
    lines.append("")

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


def build_wake_prompt(ctx: WakeContext) -> str:
    lines: list[str] = []
    _core(ctx, lines)
    _task_extras(ctx, lines)
    # Every system→agent message ends with the SAME token-location footer so even a weak
    # model always knows where its token lives — unconditional, identical to the invite,
    # skill-install and onboarding prompts (#80). No task-wake ever goes out without it.
    return "\n".join(lines) + agent_prompt_footer(ctx.credential_file)


# ── the orchestration-cadence extra (FR-044a, FR-054) ────────────────────────────

CADENCE_HEADING = "## The snags this sweep found"

_SNAG_HEADINGS: dict[str, str] = {
    "silent": "Quiet, nobody working on them",
    "due_soon": "Due soon",
    "blocked": "Blocked",
    "awaiting_leader": "Waiting on your own decision",
}


def cadence_detail(snags: Sequence[Snag]) -> str:
    """The extra a cadence wake carries, naming every snag it is being woken for (FR-054).

    An extra, not a packet: this leaves by the project door, where the Leader's own chat
    prompt supplies the four-part core. "Time to look at the board" is the wake this
    requirement exists to forbid — it costs a turn and hands over nothing, so the Leader
    has to go and re-derive what the sweep already knew. Every line here names a task the
    Leader can open.

    Grouped by kind rather than listed flat because the four kinds want four different
    responses — a stuck task needs unblocking, a task waiting on the Leader needs a
    decision — and a flat list makes the reader sort them again.
    """
    lines = [CADENCE_HEADING, ""]
    by_kind: dict[str, list[Snag]] = {}
    for snag in snags:
        by_kind.setdefault(str(snag.kind), []).append(snag)

    for kind, heading in _SNAG_HEADINGS.items():
        group = by_kind.get(kind)
        if not group:
            continue
        lines.append(f"**{heading}**")
        lines.extend(f"- {s.detail}" for s in group)
        lines.append("")

    lines.append(
        "This is a scheduled sweep, not a new task handed to you. Work through the points "
        "above: unblock what is stuck, chase whoever owes an update, judge what is waiting "
        "on you, or write down why something stays as it is."
    )
    return "\n".join(lines)
