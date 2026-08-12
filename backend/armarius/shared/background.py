"""Cleanup that runs on a bare background task, where a failure has nobody to report to."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable

from armarius.shared.logging import get_logger

logger = get_logger(__name__)

DEFAULT_ATTEMPTS = 3
DEFAULT_DELAY_SECONDS = 0.05


async def settle(
    what: str,
    action: Callable[[], Awaitable[None]],
    *,
    attempts: int = DEFAULT_ATTEMPTS,
    delay_seconds: float = DEFAULT_DELAY_SECONDS,
) -> bool:
    """Run a last-resort cleanup, retrying a lost write race. Never raises.

    Fire-and-forget work has no caller. An exception leaving such a task is retrieved by
    nobody, so whatever the cleanup was meant to settle simply stays unsettled and the
    only trace is a warning at interpreter shutdown — which is how one refused write turns
    into a project that quietly stops moving. Both halves of this function exist for that.

    **Retrying**, because the ordinary failure here is transient. Two turns finishing at
    the same instant both go to write, and the loser is refused a lock it could have had a
    moment later. Each attempt opens its own transaction, which is what makes the retry
    sound rather than hopeful: it reads a fresh snapshot instead of trying to finish one
    that has already been overtaken.

    The action must therefore be safe to run twice, and that is a real constraint on what
    may be passed here, not a hope about it. Two things make it true: the action re-reads
    and re-decides inside each attempt, so a second pass over already-settled state does
    nothing; and nothing it does *after* its commit is allowed to throw. An action that
    writes, commits, and then fails on the way out has half-happened — running it again
    cannot undo or complete that half, and the retry only piles more on top.

    **Reporting**, because giving up quietly is the very failure this guards against.
    What could not be settled is said once, at ERROR, naming the thing left undone.

    Every exception is retried rather than a curated list of database errors: telling a
    lock refusal apart from a permanent fault means naming driver codes, and which driver
    sits under this call is exactly what the application layer must not know (Constitution
    III). Being wrong costs a few attempts and a log line.

    Cancellation is not caught. A process being told to stop must not be held up by
    retries, and the caller unwinding is itself the reason the cleanup is running.

    Returns whether the action settled.
    """
    for attempt in range(1, attempts + 1):
        try:
            await action()
            return True
        except Exception:
            if attempt == attempts:
                logger.exception("gave up after %d attempts: could not %s", attempts, what)
                return False
            logger.warning("attempt %d failed: could not %s — retrying", attempt, what)
            await asyncio.sleep(delay_seconds)
    return False  # pragma: no cover - the loop always returns
