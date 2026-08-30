"""Placement — the one place an agent works, fixed when the agent is created (FR-007).

An agent does not float. It is put somewhere at birth, it stays there for life, and if that
somewhere stops working the agent is offline rather than quietly moved. Moving an agent is a
decision a person makes by replacing it, never something the system does behind their back.

What this layer is allowed to know about that place is deliberately thin: it exists, it
belongs to a workspace, and it is open for work or closed with a reason. It knows nothing
about *what* the place is or *where* it physically sits — that is infrastructure's, and the
whole point of keeping it there is that a second kind of place can arrive without a single
line of business logic being reopened (Constitution III, FR-035, FR-037).

The reason travels as a code, never a sentence: two audiences read it in two languages, and
only the edge that knows which reader it is talking to can turn it into words (Constitution
VII, FR-084a).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from uuid import UUID

from armarius.shared.errors import CodedError


class OptionNotOffered(CodedError):
    """A setting or value was chosen that the place does not take (FR-007k)."""

# An agent that was never put anywhere. Stated here rather than wherever the absence is
# noticed, because it is the one not-ready reason this layer can name on its own: no
# knowledge of what a place is goes into knowing an agent has none (FR-007f).
NOT_PLACED = "not_placed"

# The place is shut and said nothing about why. Rare, and kept as a code anyway — a screen
# that shows an agent offline with a blank space beside it is the failure FR-006c names.
PLACEMENT_NOT_READY = "placement_not_ready"


class OptionSource(StrEnum):
    """How firmly a place knows the values it listed.

    The distinction is the whole reason a value can be checked at all. A place that stated
    its **complete** set can have a choice measured against it; a place that named a few by
    way of example cannot, and treating its examples as the only answers would refuse a
    perfectly good value the day the tool behind it gains one more.
    """

    #: The place stated the whole set. A value outside it is refused.
    COMPLETE = "tool_declared"
    #: The place named some by way of illustration. Anything is accepted.
    EXAMPLES = "tool_examples"
    #: The set was supplied by whatever runs the place rather than stated by it. Treated as
    #: complete: something did assert these are the values.
    CARRIED = "known_names"

    def is_complete(self) -> bool:
        return self is not OptionSource.EXAMPLES


@dataclass(frozen=True)
class PlacementOption:
    """One setting this place accepts for an agent put here, and what it takes for it.

    Deliberately shapeless to this layer: `key` is a name, `values` are strings, and nothing
    here knows that one of them means *model* or that another only exists on one kind of
    tool. That is what lets a second kind of place arrive — with a third setting, or a
    fourth — without a line of business logic being reopened (Constitution III, FR-007k).
    """

    key: str
    values: tuple[str, ...] = ()
    source: OptionSource = OptionSource.EXAMPLES


@dataclass(frozen=True)
class Placement:
    id: UUID
    workspace_id: UUID
    # Open for work. A closed placement still exists and still holds every agent that was
    # put there — those agents are offline, which is a state with a defined meaning rather
    # than a silent failure (FR-007f).
    ready: bool = False
    not_ready_reason: str | None = None
    # What a person may choose for an agent put here (FR-007k). Empty is ordinary and means
    # this place offers nothing to choose — every agent on it runs on whatever the thing
    # behind it defaults to, which is exactly what FR-007k says an unset choice does.
    options: tuple[PlacementOption, ...] = ()

    def refuse_unchosen(self, chosen: dict[str, str]) -> None:
        """Refuse settings this place never offered, or values it does not take.

        **Checked here rather than at the screen**, because the screen is one of two callers
        and the other is whoever calls the API directly. A list rendered from the same data
        keeps an honest person right; only this keeps everybody right.

        A blank value is not a choice and is never refused: FR-007k says leaving a setting
        empty means the tool's own default, so an empty string has to survive the trip.
        """
        offered = {option.key: option for option in self.options}
        for key, value in chosen.items():
            option = offered.get(key)
            if option is None:
                raise OptionNotOffered("placement_option_unknown", option=key)
            if not value:
                continue
            if option.source.is_complete() and value not in option.values:
                raise OptionNotOffered(
                    "placement_option_value_unsupported", option=key, value=value
                )
