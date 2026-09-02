"""A counter that says *not yet*, and nothing else.

A door with no limit costs a stranger nothing to knock on. That is the whole reason this
exists: not to make a secret harder to guess — the link code's own entropy and its ten
minutes do that — but to put a price on knocking, so that one machine cannot make this
server do unbounded work for free (RFC 8628 §5.2).

Two decisions worth stating, because both are about the keys being **supplied by the
caller**:

  * **A fixed window, not a sliding one.** A sliding window keeps one timestamp per call,
    so a key's memory grows with its budget; multiplied by the number of keys a stranger
    can invent, that is a second way in. A fixed window keeps a start and a count — two
    fields, whatever the budget. It admits up to twice the allowance across a boundary,
    which does not matter to a governor: the point is that the rate is *bounded*, not that
    it is exact.
  * **The table has a ceiling, and hitting it refuses rather than grows.** A limiter that
    can be made to eat memory has turned into the attack it was built to stop. Under a
    flood, new keys are turned away and keys already in the table keep working — the
    direction that keeps a machine already mid-handshake going.

Deliberately in-process, with no shared store behind it. Two consequences, both accepted:
a restart forgets, and N replicas make the effective ceiling N times the number here. Both
are bounded and neither is what stands between a stranger and a code — a counter that
needs a round trip of its own to answer would cost more than the request it is guarding.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta

from armarius.shared.clock import utcnow


@dataclass(frozen=True)
class Allowance:
    """How many calls, in how long."""

    calls: int
    per: timedelta

    @property
    def seconds(self) -> int:
        """The window as whole seconds — what a `Retry-After` header is measured in."""
        return max(1, int(self.per.total_seconds()))


@dataclass
class _Window:
    """One key's window: when it opened, and how much has been spent since."""

    opened_at: datetime
    spent: int


class FixedWindow:
    """How often one key may pass. Not thread-safe, and does not need to be: the server
    runs one event loop and every method here returns without awaiting, so no two calls are
    ever inside it at once."""

    def __init__(
        self,
        allowance: Allowance,
        *,
        keys_kept: int,
        clock: Callable[[], datetime] = utcnow,
    ) -> None:
        self._allowance = allowance
        self._keys_kept = keys_kept
        self._clock = clock
        self._windows: dict[str, _Window] = {}

    @property
    def allowance(self) -> Allowance:
        return self._allowance

    def wait_for(self, key: str) -> float:
        """Seconds this key must wait, spending nothing. ``0.0`` means go ahead.

        Asked *before* the work a door does, so that a caller already over its budget is
        turned away without the read it wanted paying for.
        """
        return self._wait(key, self._clock())

    def charge(self, key: str) -> float:
        """Record one call against this key. ``0.0`` if it fitted.

        A call that does not fit records nothing: a budget that keeps counting while it
        refuses would extend its own window every time a caller tried again, which turns a
        one-minute wait into a permanent lockout for anyone who retries.
        """
        now = self._clock()
        wait = self._wait(key, now)
        if wait > 0.0:
            return wait
        window = self._windows.get(key)
        if window is None:
            if len(self._windows) >= self._keys_kept:
                self._forget(now)
            if len(self._windows) >= self._keys_kept:
                # Every key in a full table is live. Turning this one away is the only
                # answer left that does not grow the table (see the module docstring).
                return float(self._allowance.seconds)
            self._windows[key] = _Window(opened_at=now, spent=1)
            return 0.0
        window.spent += 1
        return 0.0

    def _wait(self, key: str, now: datetime) -> float:
        """The answer to `wait_for`, and the expiry housekeeping that goes with it."""
        window = self._windows.get(key)
        if window is None:
            return 0.0
        if now - window.opened_at >= self._allowance.per:
            del self._windows[key]
            return 0.0
        if window.spent < self._allowance.calls:
            return 0.0
        return max(0.0, (window.opened_at + self._allowance.per - now).total_seconds())

    def _forget(self, now: datetime) -> None:
        """Drop every window that has run out. Called only when the table is full, so the
        cost of walking it is paid by whoever filled it."""
        dead = [
            key
            for key, window in self._windows.items()
            if now - window.opened_at >= self._allowance.per
        ]
        for key in dead:
            del self._windows[key]
