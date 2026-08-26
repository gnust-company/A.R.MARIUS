"""What one agent is given when a run is handed over — the shape, not the contents.

Two layers have to agree on this: the business layer builds it (the message is assembled
from the agent's own instructions, the project's context and the reason for the wake), and
the delivery layer carries it out to whatever will run the agent. Neither should have to
import the other to name the thing they are passing, so the name lives here.

Nothing in this file knows *where* the agent runs (Constitution III). A packet is the same
packet whether it is handed to a process on somebody's laptop or to a service across the
network — what changes is who picks it up, and that is not this layer's business.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class SkillBundle:
    """One skill, whole: its directory name and every file in it.

    `files` maps a path **relative to the skill's own directory** to that file's contents,
    so `SKILL.md` and `ref/api.md` describe a two-file skill. Relative on purpose — whoever
    lays these out decides the parent directory, and a path that could climb out of it
    would be a path that could write anywhere.
    """

    name: str
    files: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class WorkPacket:
    """Everything the run needs that is not the run itself.

    `prompt` is the whole message, in English (Constitution VII), assembled here rather
    than wherever the agent happens to run: it is built from the agent's instructions and
    the project's context, and both of those rules live on this side.
    """

    prompt: str
    skills: tuple[SkillBundle, ...] = ()
