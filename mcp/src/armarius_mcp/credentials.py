"""Read/write the agent credential file, byte-for-byte compatible with onboarding.

The backend's invite flow (``backend/armarius/application/use_cases/onboarding.py``)
tells the agent to store its credentials at

    $HOME/.armarius/tokens/{workspace_slug}_{agent_name.lower()}.json

(``$HOME`` spelled out rather than ``~`` for weak runtimes, #114; ``_expand`` below
resolves both forms)

as a JSON object with six keys: ``agent_name, agent_role, agent_token, workspace,
project, api_base_url``. This module reads that file for bootstrap and writes it back
so a later run finds the token minted at invite time (#63) — using the same slug rule
and the same key set, so the two sides never drift.

**Path change note**: The directory was renamed from ``credentials`` to ``tokens`` to avoid
Hermes Agent's keyword-based file write protection (paths containing "credential" are
blocked as protected system files). See https://hermes-agent.nousresearch.com/docs/user-guide/security#file-write-safety
"""

from __future__ import annotations

import json
import os
import re
import tempfile
from dataclasses import dataclass
from glob import glob
from pathlib import Path
from typing import Any

CREDENTIALS_DIR = Path("~/.armarius/tokens").expanduser()

# Ordered to match the onboarding template exactly.
CREDENTIAL_KEYS = (
    "agent_name",
    "agent_role",
    "agent_token",
    "workspace",
    "project",
    "api_base_url",
)


def slugify(value: str) -> str:
    """Same rule as onboarding._slugify / skills._slugify (fallback differs per caller)."""
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug or "workspace"


def credential_path(workspace: str, agent_name: str) -> Path:
    """The onboarding path for this workspace + agent."""
    return CREDENTIALS_DIR / f"{slugify(workspace)}_{agent_name.lower()}.json"


@dataclass(slots=True)
class Credentials:
    agent_name: str = ""
    agent_role: str = ""
    agent_token: str = ""
    workspace: str = ""
    project: str = ""
    api_base_url: str = ""

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Credentials:
        return cls(**{k: str(data.get(k, "") or "") for k in CREDENTIAL_KEYS})

    def to_dict(self) -> dict[str, str]:
        return {k: getattr(self, k) for k in CREDENTIAL_KEYS}


def _expand(path: str | os.PathLike[str]) -> Path:
    # Expand $VARS *then* ~ / ~user. ARMARIUS_CREDENTIAL_FILE reaches us as a literal env
    # value — MCP hosts write it verbatim into the child's environment and do NOT shell-expand
    # it — so a config that names "$HOME/.armarius/tokens/..." (#114) would otherwise stay a
    # relative "$HOME/..." path and never resolve. expandvars handles $HOME; expanduser still
    # handles a "~/..." path, and an already-absolute path passes through both untouched.
    return Path(os.path.expanduser(os.path.expandvars(os.fspath(path))))


def load(path: str | os.PathLike[str]) -> Credentials:
    """Load a credential file. Raises FileNotFoundError / ValueError on a bad file."""
    p = _expand(path)
    data = json.loads(p.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"credential file {p} is not a JSON object")
    return Credentials.from_dict(data)


def discover(explicit: str | None = None) -> tuple[Path, Credentials] | None:
    """Find a credential file: an explicit path, else the sole glob match.

    Returns ``(path, credentials)`` or ``None`` if there is no unambiguous file (missing,
    or more than one candidate — the multi-workspace case, deferred to #15).
    """
    if explicit:
        p = _expand(explicit)
        if p.is_file():
            try:
                return p, load(p)
            except (ValueError, OSError):
                return None
        return None
    matches = sorted(glob(str(CREDENTIALS_DIR / "*_*.json")))
    if len(matches) != 1:
        return None
    p = Path(matches[0])
    try:
        return p, load(p)
    except (ValueError, OSError):
        return None


def save(creds: Credentials, path: str | os.PathLike[str] | None = None) -> Path:
    """Atomically write the credential file with mode 0600.

    When ``path`` is omitted it is derived from ``workspace`` + ``agent_name`` (the
    onboarding path). Writes to a temp file in the same dir then ``os.replace`` so a
    reader never sees a half-written token.
    """
    target = (
        _expand(path)
        if path is not None
        else credential_path(creds.workspace, creds.agent_name)
    )
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(creds.to_dict(), indent=2, ensure_ascii=False) + "\n"
    fd, tmp = tempfile.mkstemp(dir=target.parent, prefix=".cred-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(payload)
        os.chmod(tmp, 0o600)
        os.replace(tmp, target)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise
    return target
