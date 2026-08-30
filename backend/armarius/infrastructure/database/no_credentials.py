"""One door in front of everything written down about a run, so a new writer inherits it.

There are three places a row is written into `run_events`, and until now only one of them
was guarded: the door daemons knock on. The other two are this side writing about itself —
the message it composed for the agent, and the events of a run it is executing in its own
process. Both of those roads are honest today; the point is that neither of them *has* to
be, and nothing was standing between them and the table (FR-048c).

The tempting fix is a third copy of the check, at the second write. That is how two becomes
three and three becomes four, and the fourth is the one somebody forgets. So the check moved
to the one place all of them already pass through whether they mean to or not: the moment
the row is written. A writer added next year does not have to know this rule exists in
order to be held to it.

**Why the door upstairs stays.** It is not made redundant by this and it is not the same
check twice for the sake of it. The door answers the daemon with a named code in time for
it to drop the batch and fix its masking (T141); this one answers nobody, because by the
time a row is being written the only useful thing left to do is not write it. Door and
store, the same shape as T098 — one of them tells you, the other one is true.

**Why the blob table too.** A long event is kept in two pieces (FR-049): an opening slice
on the row, the whole of it beside. A guard that read only the slice would be a guard
against a secret in the first two kilobytes, which is not the rule anybody meant.

**Why the wake row too.** It keeps the exact message that went out, and it is filled in on
the road that does not touch `run_events` at all. Guarding the log and not that would leave
the same text unguarded under a different column name.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import event

from armarius.shared.credentials import carries_our_credential
from armarius.shared.errors import BadRequest


def refuse_credentials_in(model: type, field: str) -> None:
    """Refuse to write a row of `model` whose `field` carries one of our own credentials.

    Insert *and* update. Two of the three tables here are append-only and the third is only
    ever filled in once, so the update half will not fire in the ordinary run of things —
    which is the reason to register it rather than not. "This table is never updated" is a
    habit of the code as it stands today, and a guard that rests on a habit is a guard with
    a date on it.

    Refusing rather than masking, for the same reason the door refuses: a payload quietly
    rewritten on the way to storage makes the log say a thing the agent did not say, and
    FR-048 puts masking on the machine that holds the secret, not here. Failing the write is
    loud on every road that reaches it — the claim gives the run back and says so in the log,
    the in-process runner fails the run — and on none of them does the secret land.
    """

    def _look(_mapper: Any, _connection: Any, target: Any) -> None:
        if carries_our_credential(getattr(target, field, None)):
            raise BadRequest("credential_in_the_clear")

    event.listen(model, "before_insert", _look)
    event.listen(model, "before_update", _look)
