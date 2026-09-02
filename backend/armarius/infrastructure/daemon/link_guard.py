"""What the three link doors cost to knock on (FR-001, RFC 8628 §5.2).

The link code is already hard to guess: eight characters from an alphabet of thirty-two,
alive for ten minutes, good for one use. Nothing here improves on that, and nothing here is
meant to — an attacker's odds are set by the code, not by a counter. What a counter buys is
the other half of the same requirement: a stranger must not be able to make this server
work for free, and a machine must not be able to ask faster than the pace it was handed.

Three budgets, because the three doors are knocked on by different callers for different
reasons:

  * **A person's misses.** `GET /v1/machines/link/{code}` says whether a code is live, and
    `POST …/approve` is what a guess would be *for* — approving a stranger's waiting
    machine into your own workspace. One budget covers both, not two: they are one activity
    (look, then approve), and two budgets would only double the guesses per minute.

    Only a **miss** is charged. A person who types a code that is really theirs is never
    limited however fast they work, and someone reading codes off a list runs out
    immediately. Charging every call would have limited exactly the wrong person.

  * **One code's pace.** The daemon is handed a polling interval and told to keep to it.
    The budget is derived from that interval and the code's own life rather than being a
    number of its own, so the ceiling cannot drift out of step with the pace the server
    itself advertises. A daemon that honours the interval never comes near it; one hammering
    the door is slowed to the pace it was given.

  * **The whole poll door.** It is the only door in the system with no credential at all,
    so nothing else bounds what a stranger can make it do. This one is a load shed, and the
    refusal is deliberately the same as the one above: telling a caller which budget it hit
    would say something about everybody else's traffic.

Per-code counting is worth being honest about: it does **not** slow guessing down, because
every guess is a different code and therefore a fresh budget. It is the whole-door budget
that bounds a guesser, and the code's entropy that makes guessing pointless. The per-code
budget is there for the caller that actually exists — a daemon in a loop.
"""

from __future__ import annotations

from datetime import timedelta

from armarius.infrastructure.daemon.enrollment import normalise_code
from armarius.infrastructure.security.rate_limit import Allowance, FixedWindow
from armarius.shared.config import settings
from armarius.shared.errors import TooManyRequests

#: One key for the whole-door budget. A constant rather than a caller-supplied string,
#: which is the point of it: this budget is what everybody shares.
_EVERYONE = "*"


class LinkDoorGuard:
    """The counters in front of the three link doors."""

    def __init__(
        self,
        *,
        misses_per_minute: int | None = None,
        polls_per_minute: int | None = None,
        code_ttl_seconds: int | None = None,
        poll_interval_seconds: int | None = None,
    ) -> None:
        misses = misses_per_minute or settings.daemon_link_misses_per_minute
        polls = polls_per_minute or settings.daemon_link_polls_per_minute
        ttl = code_ttl_seconds or settings.daemon_link_code_ttl_seconds
        interval = poll_interval_seconds or settings.daemon_link_poll_interval_seconds

        self._misses = FixedWindow(
            Allowance(calls=misses, per=timedelta(minutes=1)),
            # One entry per person who has recently mistyped a code. Bounded by the number
            # of accounts, not by anything a stranger can invent.
            keys_kept=4_096,
        )
        # Twice what a well-behaved daemon spends over the whole life of its code: it polls
        # every `interval` for at most `ttl`, so anything past double that is a machine not
        # keeping to the pace it was told.
        self._per_code = FixedWindow(
            Allowance(
                calls=max(2, (ttl // max(1, interval)) * 2),
                per=timedelta(seconds=ttl),
            ),
            # Enough for every code the whole-door budget above could let through in one
            # code lifetime, so that this ceiling is never the binding one in practice.
            keys_kept=8_192,
        )
        self._all_polls = FixedWindow(
            Allowance(calls=polls, per=timedelta(minutes=1)), keys_kept=1
        )

    # ── the person's two doors ───────────────────────────────────────────────────

    def before_a_person_asks(self, user_id: str) -> None:
        """Refuse if this person has already missed too often this minute."""
        wait = self._misses.wait_for(user_id)
        if wait > 0.0:
            raise TooManyRequests("daemon_link_guessed_too_often", retry_after=wait)

    def a_person_missed(self, user_id: str) -> None:
        """Charge one miss. Called after the door has found nothing behind the code.

        Never raises. The caller is on its way to raising *not found*, which is the answer
        this person is owed; turning it into *too many attempts* at the last moment would
        tell them the code they typed was the one that used up their budget.
        """
        self._misses.charge(user_id)

    # ── the machine's door ───────────────────────────────────────────────────────

    def before_a_machine_polls(self, code: str) -> None:
        """Refuse a poll that is either too fast for its code or too much for the door.

        The whole-door budget is charged first and unconditionally, so that a flood of
        invented codes is counted even though each of them has a budget of its own.
        """
        wait = self._all_polls.charge(_EVERYONE)
        if wait > 0.0:
            raise TooManyRequests("daemon_link_polled_too_often", retry_after=wait)
        # Keyed on the canonical code, not on what was typed. Keying on the raw string
        # would let punctuation — `kq7f m2xd`, `KQ7F-M2XD` — buy a fresh budget for the
        # same code.
        wait = self._per_code.charge(normalise_code(code))
        if wait > 0.0:
            raise TooManyRequests("daemon_link_polled_too_often", retry_after=wait)
