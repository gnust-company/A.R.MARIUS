"""What one of this system's own credentials looks like — written down once (FR-048b).

Masking a secret belongs on the machine that holds it, where it can be done by **value**:
the daemon is handed the run's token and the machine's, so it looks for those two exact
strings and finding them is a certainty rather than a guess (FR-048). This side cannot do
that. It keeps only hashes, so there is nothing here to compare a payload against, and the
one class of secret it can still recognise is the class whose **shape** it mints itself.

That is why this module is small and why it is anchored on two prefixes rather than on
entropy or length. A guard that fired on anything long and random would fire on a commit
hash, a base64 image, an agent's own API response — and since T141 a refused batch is a
batch dropped for good, every false positive costs a slice of a run's log.

It lives in `shared` because the two roads that need it sit on opposite sides of the
layering: the door that daemons knock on is infrastructure, and the table that everything
is finally written to is reached from the application layer as well. Neither may import the
other, and a second copy of this pattern is a second copy to drift.
"""

from __future__ import annotations

import json
import re

#: How a machine token starts. Public because the shape has to be recognisable somewhere a
#: machine token never belongs, not only where one is minted.
MACHINE_TOKEN_PREFIX = "armd_"

#: How a run token starts. Public for the same reason.
RUN_TOKEN_PREFIX = "armr_run_"

#: How much url-safe text has to follow one of our prefixes before it counts as a credential
#: rather than a name. `secrets.token_urlsafe(32)` is 43 characters, so this leaves three to
#: spare — narrow on purpose in the other direction too: a guard that also fired on
#: `armd_config_name` would cost a batch of a run's log for a variable name.
#:
#: Three characters is not much margin, and the margin is not obvious from here — it lives in
#: an argument to `token_urlsafe` in two other modules. `test_secret_redaction.py` asserts the
#: property directly (*a token this system mints is one this guard recognises*), so shortening
#: a token is a named failure rather than a door that quietly stops closing.
CREDENTIAL_TAIL_FLOOR = 40

#: One of this system's own credentials, sitting somewhere it was never meant to be.
OUR_CREDENTIALS = re.compile(
    rf"(?:{re.escape(RUN_TOKEN_PREFIX)}|{re.escape(MACHINE_TOKEN_PREFIX)})"
    rf"[A-Za-z0-9_-]{{{CREDENTIAL_TAIL_FLOOR},}}"
)


def carries_our_credential(value: object) -> bool:
    """Whether this text — or anything nested anywhere inside this structure — is one.

    A payload is a tree, and a secret is as dangerous in a map key three levels down as it
    is at the top. Rendering the whole of it to text and searching that is what makes the
    answer independent of the shape it arrived in; walking the tree by hand would mean a
    list of container types, and the first type left off the list is the way through.
    """
    text = value if isinstance(value, str) else json.dumps(value, default=str)
    return OUR_CREDENTIALS.search(text) is not None
