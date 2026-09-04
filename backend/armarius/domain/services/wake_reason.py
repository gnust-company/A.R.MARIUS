"""Why an agent was woken — kept as data, not as a finished sentence (Constitution VII).

The same answer has two readers who do not read the same language. The agent gets the wake
packet, which is English end to end because an agent has no interface language to pick from.
The patron reads the very same line on the agent screen, in whichever language they chose.

A sentence written once at wake time can only ever serve one of them. So nothing here writes
a sentence: a cause is a **code plus its parameters**, and each side renders it — English
below for the packet, the interface's own phrase table for the screen.

The codes are a closed list. That is the point: a cause nobody has worded cannot be woken
for, which is the same discipline the two closed wake-cause lists apply to *who* may be
woken (FR-047, FR-048).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

# ── the closed list ───────────────────────────────────────────────────────────
#
# English, because this is the agent's copy. Placeholders are filled from `params`; a
# missing parameter degrades to the marker below rather than raising, since failing to wake
# an agent is far worse than waking it with one vague noun.

_UNKNOWN_PARAM = "(unknown)"

ENGLISH: dict[str, str] = {
    # ── event wakes ──
    "assigned": "You were assigned to this task.",
    "mentioned": "You were mentioned in the task thread.",
    "new_comment": "A new comment was posted on a task you are responsible for.",
    "dependency_cleared": (
        "{blocker} is done, so this task is no longer blocked and is ready to start."
    ),
    "requirement_changed": (
        "The patron changed this task while you were on it ({fields}). "
        "Re-read the task before you carry on — what you were told first may no "
        "longer be what is wanted."
    ),
    "output_rejected": "Your output was sent back for rework: {note}",
    "artifact_missing": (
        "Your published output is no longer in the store, so the task came back to you: "
        "{files}. Publish it again."
    ),
    "brief_review": (
        "This task has been sent back {rounds} times. Review the brief and the acceptance "
        "criteria rather than the work itself."
    ),
    # ── self-wakes decided by the wake policy ──
    "run_dropped": "Your last run was dropped before it finished. Resume the task session.",
    "work_unfinished": "You left a recorded next action behind. Continue from it.",
    "stopped_without_progress": (
        "Your last run ended without recording any progress. Say where the work stands."
    ),
    "no_reason_recorded": (
        "This task is parked with no reason recorded. Post an update saying what it waits on."
    ),
    "run_hung": "Your last run hung and the task was pulled back. Pick up from: {next_action}",
    # ── the safety net calling back (FR-059 Level 1) ──
    # One code per stall verdict rather than one code with the verdict as free text: the
    # verdict is itself a system sentence, and a system sentence passed as a parameter is
    # a sentence that escapes this table.
    "recovery_orphaned": (
        "The safety net called you back: nobody is working on this task and no wake is booked."
    ),
    "recovery_run_active": (
        "The safety net called you back: the run holding this task went quiet mid-turn."
    ),
    "recovery_wake_scheduled": (
        "The safety net called you back: you were called for this task but never started."
    ),
    "recovery_waiting_recovery": (
        "The safety net called you back: earlier re-wakes never reached you."
    ),
    "recovery_waiting_external": (
        "The safety net called you back: this task waits on something outside and is overdue."
    ),
    "recovery_unknown": "The safety net called you back: this task lost its drive.",
    # ── the Leader's own causes ──
    "task_in_review": "{task} was handed in and is waiting for your judgement.",
    "task_done": "{task} is done.",
    "batch_done": "Every task in this batch is closed.",
    "worker_asked_for_task": "A worker asked to be put on {task}.",
    "worker_handback": "A worker handed {task} back or asked a question about it.",
    "roster_complete": "The roster is full and everyone is online. Go and plan.",
    "context_change_requested": "The patron asked for changes to the project context.",
    "plan_decided": "The patron decided on the plan: {decision}.",
    "patron_rejected_output": (
        "The patron refused the output of {task}: {note}. It went back to the same worker "
        "— review what you passed and decide what has to change."
    ),
    "cadence_snags": "The orchestration sweep found {count} snag(s) on the board.",
    "escalated_to_leader": (
        "{task} has stalled and needs you to decide the next move. Attempt "
        "{attempt} of {ceiling}."
    ),
    "assignee_offline": (
        "The worker on {task} was declared offline and the task moved to blocked. "
        "Reassign it, or wait for them."
    ),
    # ── the team-building interview (FR-040c) ──
    # It is a run like any other, so its cause is written the way every other cause is.
    # Naming the two turns apart matters to whoever reads the run afterwards: one of them
    # opens a conversation and the other continues one, and a log that calls both "the
    # patron said something" cannot say which run was the first.
    "leader_chat_message": "The patron wrote to you in the project chat.",
    "onboarding_opened": "The patron opened a chat to set a project up with you.",
    "onboarding_answered": "The patron answered your question.",
    # ── the manual button ──
    "manual_wake": "The patron woke you from the dashboard.",
    "manual_wake_note": "The patron woke you from the dashboard: {note}",
}


@dataclass(frozen=True)
class WakeReason:
    """One cause, in the only form both readers can use."""

    code: str
    params: Mapping[str, str] = field(default_factory=dict)

    def render_en(self) -> str:
        """The agent's copy. An unknown code falls back to itself rather than vanishing —
        a wake that says something odd still reaches somebody; a wake that says nothing
        does not."""
        template = ENGLISH.get(self.code)
        if template is None:
            return self.code
        try:
            return template.format_map(_Defaulting(self.params))
        except Exception:  # pragma: no cover - defensive, format_map is total here
            return template

    def to_payload(self) -> dict[str, object]:
        return {"code": self.code, "params": dict(self.params)}


class _Defaulting(dict):
    """Fills a missing placeholder instead of raising."""

    def __missing__(self, key: str) -> str:
        return _UNKNOWN_PARAM


def reason(code: str, **params: object) -> WakeReason:
    """Shorthand for a call site: ``reason("dependency_cleared", blocker="TOT-1")``."""
    return WakeReason(code=code, params={k: str(v) for k, v in params.items()})


def render_en(causes: Sequence[WakeReason]) -> str:
    """Every cause, one per line, in the agent's language.

    All of them and not just the strongest: the strongest cause is what the wake is *filed*
    under, but a teammate's question that arrived alongside it is still owed an answer, and
    an agent that never sees it never answers it (FR-050).
    """
    lines = [c.render_en() for c in causes if c.render_en()]
    if not lines:
        return ""
    if len(lines) == 1:
        return lines[0]
    return "\n".join(f"• {line}" for line in lines)


def merge(existing: Sequence[WakeReason], incoming: WakeReason) -> list[WakeReason]:
    """Fold one more cause in, keeping each one exactly once.

    Sameness is code **and** parameters: two dependency-cleared causes naming two different
    blockers are two things the agent needs to know, while the same one twice is noise.
    """
    causes = list(existing)
    for c in causes:
        if c.code == incoming.code and dict(c.params) == dict(incoming.params):
            return causes
    causes.append(incoming)
    return causes


def to_payload(causes: Sequence[WakeReason]) -> list[dict[str, object]]:
    return [c.to_payload() for c in causes]


def from_payload(raw: object) -> list[WakeReason]:
    """Read causes back off a stored row.

    Anything unrecognised reads as *no structured causes*, which is exactly what a row
    written before this existed should look like — the caller then falls back to the
    sentence that row does carry.
    """
    if not isinstance(raw, list):
        return []
    out: list[WakeReason] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        code = item.get("code")
        if not isinstance(code, str) or not code:
            continue
        params = item.get("params")
        out.append(
            WakeReason(
                code=code,
                params={str(k): str(v) for k, v in params.items()}
                if isinstance(params, dict)
                else {},
            )
        )
    return out
