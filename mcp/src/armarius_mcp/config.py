"""Resolve the server's runtime config: base URL + token + identity.

Precedence (see README):

    token     ARMARIUS_AGENT_TOKEN  →  credential file `agent_token`  →  none
    base URL  ARMARIUS_PUBLIC_BASE_URL  →  credential file `api_base_url`
              →  GET {default}/v1/meta probe  →  default http://localhost:8080

Under operator-invite (issue #63) the agent receives its token in the setup prompt
Armarius pushes via its gateway, so there is no ``enroll``/``claim`` bootstrap (issue
#64). If no token is found the server still starts; token-required tools then return a
clear "save the token from your setup prompt" error.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field

import httpx

from armarius_mcp.credentials import Credentials, discover
from armarius_mcp.logging_setup import get_logger

DEFAULT_BASE_URL = "http://localhost:8080"

log = get_logger(__name__)


@dataclass(slots=True)
class Config:
    base_url: str
    token: str | None = None
    credential_path: str | None = None
    credentials: Credentials | None = None
    # Identity hints (from env / credential file) — purely informational.
    agent_name: str = ""
    agent_role: str = ""
    workspace: str = ""
    project: str = ""
    request_timeout_seconds: float = 30.0

    # Bootstrap args the agent may not pass explicitly (env fallbacks).
    env: dict[str, str] = field(default_factory=dict)

    @property
    def has_token(self) -> bool:
        return bool(self.token)


def _env(name: str) -> str | None:
    val = os.environ.get(name)
    return val.strip() if val and val.strip() else None


def _float_env(name: str, default: float) -> float:
    raw = _env(name)
    if raw is None:
        return default
    try:
        return float(raw)
    except ValueError:
        log.warning("ignoring non-numeric %s=%r", name, raw)
        return default


def _probe_meta(base_url: str, timeout: float) -> str | None:
    """Return the backend's advertised public_base_url, or None if unreachable."""
    try:
        resp = httpx.get(f"{base_url.rstrip('/')}/v1/meta", timeout=timeout)
        resp.raise_for_status()
        url = resp.json().get("public_base_url")
        return str(url).rstrip("/") if url else None
    except (httpx.HTTPError, ValueError, TypeError):
        return None


def resolve_config(*, probe: bool = True) -> Config:
    """Build the runtime Config from env + credential file (+ optional /v1/meta probe)."""
    cred_hit = discover(_env("ARMARIUS_CREDENTIAL_FILE"))
    cred_path = str(cred_hit[0]) if cred_hit else None
    creds = cred_hit[1] if cred_hit else None

    token = _env("ARMARIUS_AGENT_TOKEN") or (creds.agent_token if creds else None) or None

    request_timeout = _float_env("ARMARIUS_MCP_REQUEST_TIMEOUT", 30.0)
    base_url = (
        _env("ARMARIUS_PUBLIC_BASE_URL")
        or (creds.api_base_url if creds and creds.api_base_url else None)
    )
    if base_url is None:
        base_url = (probe and _probe_meta(DEFAULT_BASE_URL, request_timeout)) or DEFAULT_BASE_URL
    base_url = base_url.rstrip("/")

    return Config(
        base_url=base_url,
        token=token,
        credential_path=cred_path,
        credentials=creds,
        agent_name=_env("ARMARIUS_AGENT_NAME") or (creds.agent_name if creds else "") or "",
        agent_role=_env("ARMARIUS_AGENT_ROLE") or (creds.agent_role if creds else "") or "",
        workspace=_env("ARMARIUS_WORKSPACE") or (creds.workspace if creds else "") or "",
        project=_env("ARMARIUS_PROJECT") or (creds.project if creds else "") or "",
        request_timeout_seconds=request_timeout,
    )
