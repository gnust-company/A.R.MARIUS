"""Which failures are worth trying again, and which are waiting on a person (FR-032).

Every automatic retry in this system spends something real: an agent turn, a slot on
somebody's machine, and the minutes between attempts. That is a good trade when the next
attempt might land — a network that dropped, a machine that rebooted, a gateway that was
briefly busy. It is a pure loss when the next attempt cannot land, and the losses are the
expensive shape: a run that ends the same way every time still ends *late*, and the person
who could have fixed it in a minute is told half an hour after the fact, by a safety net,
instead of at the moment the machine already knew.

The three endings named below are that second shape, and each of them is a wall:

  * **an exhausted quota** is a property of the workplace, not of the agent (FR-007c). The
    provider has stopped answering for that login, and it will keep not answering until a
    person tops it up or signs in somewhere else.
  * **a credential that was revoked or has expired** fails identically on every attempt,
    which is exactly why FR-014f puts it here by name. Nothing on the machine can mint
    another one.
  * **a workplace configured for work it cannot do** — a missing permission, a setting
    that has to be turned on by hand — is a decision somebody made and only somebody can
    unmake.

**An ending nobody has classified is treated as worth retrying.** That default is not
optimism, it is the cheaper mistake. Guess *transient* wrongly and the existing budget
bounds the loss to a handful of attempts before a person is asked anyway; guess *needs a
person* wrongly and every unfamiliar hiccup — a new CLI's new word for a timeout — becomes
an interruption, and an alarm that cries wolf is an alarm that gets muted.

Codes rather than sentences, for the reason every verdict in this system is a code: this
one is read by the wake policy, written into the record, and rendered on a screen in the
reader's own language (Constitution VII).
"""

from __future__ import annotations

#: The workplace's provider has nothing left to give on this login (FR-007c).
QUOTA_EXHAUSTED = "quota_exhausted"
#: The credential the work was carried out with is no longer good — revoked, or expired
#: (FR-014f). Retrying it fails the same way every time.
CREDENTIAL_REJECTED = "credential_rejected"
#: The workplace is set up for something it cannot do: a permission it was never granted,
#: a setting that has to be turned on by hand.
MISCONFIGURED = "misconfigured"

#: The closed list. Closed on purpose: a failure nobody has decided about is one the system
#: may still try again, so an open list would quietly turn every unknown into an alarm.
NEEDS_A_PERSON: frozenset[str] = frozenset(
    {QUOTA_EXHAUSTED, CREDENTIAL_REJECTED, MISCONFIGURED}
)

#: What each ending means, in English, for records and for anything said to an agent
#: (Constitution VII). The screen renders the same code in the reader's own language.
NEEDS_A_PERSON_ENGLISH: dict[str, str] = {
    QUOTA_EXHAUSTED: "this workplace has run out of provider quota",
    CREDENTIAL_REJECTED: "the credential this work was carried out with is no longer good",
    MISCONFIGURED: "this workplace is not set up for the work it was given",
}


def needs_a_person(code: str | None) -> bool:
    """Whether this ending is a wall the system cannot get past by trying again.

    Anything unrecognised — including nothing at all, which is what a machine with no
    verdict reports — comes back False. See the module docstring for why that is the
    cheaper of the two mistakes.
    """
    return code in NEEDS_A_PERSON


def english(code: str | None) -> str:
    """The English rendering of an ending, for the record and for the agent.

    An unrecognised code degrades to naming itself rather than raising: a verdict written
    by a newer machine must still read as words in an older reader, and losing the whole
    record to a KeyError would be worse than losing the phrasing.
    """
    if not code:
        return ""
    return NEEDS_A_PERSON_ENGLISH.get(code, code)
