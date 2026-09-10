"""Reading one section out of an onboarding prompt, for the tests that check what it says.

It exists because the first two versions of that check were wrong in the same way: they looked
for a field name anywhere in the prompt, and the prompt names every field twice — once in the
FIELD PLAN the agent reads to know what to ask next, and once in the JSON example of the draft it
posts at the end. So a prompt that had dropped a field from the plan still passed, because the
name was still sitting in the JSON. Both mutation tests went green against a broken prompt.

The plan is the half that decides whether a question ever gets asked. This reads that half.
"""

from __future__ import annotations

# Where the plan stops. The long form (opening turn) lists one field per line and is followed by a
# blank line; the short form (every turn after) is one line and is followed by the tool templates.
_ENDS_THE_PLAN = ("`onboarding", "project={")


def field_plan_of(prompt: str) -> str:
    """The FIELD PLAN section of ``prompt`` — the lines an agent reads to know what to ask next.

    Anchored on a line that *starts with* ``FIELD PLAN``, not the first line that mentions it: the
    opening prompt says "working through the FIELD PLAN below" in its very first sentence, and
    anchoring there returned a section with no fields in it at all.
    """
    lines = prompt.split("\n")
    start = next(i for i, line in enumerate(lines) if line.startswith("FIELD PLAN"))
    out = [lines[start]]
    for line in lines[start + 1:]:
        if not line.strip() or any(mark in line for mark in _ENDS_THE_PLAN):
            break
        out.append(line)
    return "\n".join(out)
