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

from collections.abc import Mapping
from dataclasses import dataclass, field
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

# The place could not say who would carry the work of an agent put there. Nothing a person
# did causes this — it means the half of the system that knows what a place *is* did not
# answer — but it is refused rather than papered over, because an agent created without an
# answer would be an agent no wake could ever reach.
PLACEMENT_CARRIES_NOTHING = "placement_carries_nothing"


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
    #: The place listed what it offers right now, and takes other values too — a tool that
    #: names the models this account may pick and still runs a full model name it did not
    #: list. Worth showing whole, never worth refusing a value over.
    LISTED = "tool_listed"

    def is_complete(self) -> bool:
        return self in (OptionSource.COMPLETE, OptionSource.CARRIED)


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
    # A readable name for a value, as the place gave it. Only for the screen.
    labels: Mapping[str, str] = field(default_factory=dict)
    # Picking a value here narrows another setting to the values listed — keyed by that
    # setting's own key, so the rule reads the same whatever the settings mean. An empty list
    # is a real answer: with this value picked, the other setting takes nothing but blank.
    narrows: Mapping[str, Mapping[str, tuple[str, ...]]] = field(default_factory=dict)


@dataclass(frozen=True)
class Placement:
    id: UUID
    workspace_id: UUID
    # Who carries the work of an agent put here. An opaque key: this layer stores it, hands
    # it on, and never reads a meaning into it — nothing here compares it to a value, and
    # nothing here knows which keys exist.
    #
    # It is on the *place* because that is where the answer actually comes from. Which tool
    # carries an agent's turn follows from where the agent was put, which is a thing the
    # person choosing can see; asking them separately would be asking a question they have
    # no way to answer well, and answering it with a constant in the business layer would be
    # that layer naming a runtime (Constitution III, FR-007k).
    carried_by: str = ""
    # Open for work. A closed placement still exists and still holds every agent that was
    # put there — those agents are offline, which is a state with a defined meaning rather
    # than a silent failure (FR-007f).
    ready: bool = False
    not_ready_reason: str | None = None
    # What a person may choose for an agent put here (FR-007k). Empty is ordinary and means
    # this place offers nothing to choose — every agent on it runs on whatever the thing
    # behind it defaults to, which is exactly what FR-007k says an unset choice does.
    options: tuple[PlacementOption, ...] = ()

    def refuse_unchosen(
        self, chosen: dict[str, str], *, alongside: Mapping[str, str] | None = None
    ) -> None:
        """Refuse settings this place never offered, or values it does not take.

        **Checked here rather than at the screen**, because the screen is one of two callers
        and the other is whoever calls the API directly. A list rendered from the same data
        keeps an honest person right; only this keeps everybody right.

        A blank value is not a choice and is never refused: FR-007k says leaving a setting
        empty means the tool's own default, so an empty string has to survive the trip.

        `alongside` is what the agent is already set to. It is never measured itself — a value
        stored months ago was accepted when it was chosen — but it is the company a value being
        chosen now has to keep: a level sent on its own is measured against the model already
        saved, because that model is what it will run with (FR-007k, revised 2026-10-26).
        """
        offered = {option.key: option for option in self.options}
        settled = {**(alongside or {}), **chosen}
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
            allowed = self._allowed_beside(key, settled)
            if allowed is not None and value not in allowed:
                raise OptionNotOffered(
                    "placement_option_value_unsupported", option=key, value=value
                )

    def _allowed_beside(self, key: str, settled: Mapping[str, str]) -> set[str] | None:
        """What `key` may take given every other setting's value, or None when nothing
        narrows it. Two settings narrowing the same one leave what both allow."""
        allowed: set[str] | None = None
        for other in self.options:
            if other.key == key:
                continue
            picked = settled.get(other.key)
            if not picked:
                continue
            narrowed = other.narrows.get(picked, {}).get(key)
            if narrowed is None:
                continue
            allowed = set(narrowed) if allowed is None else allowed & set(narrowed)
        return allowed
