"""Server state: the resolved config + the HTTP client, plus token persistence.

Kept separate from ``server.py`` so the tool implementations in ``tools.py`` can be
driven with a fake ``ArmariusClient`` in unit tests (constructor injection).
"""

from __future__ import annotations

from armarius_mcp.client import ArmariusClient
from armarius_mcp.config import Config
from armarius_mcp.credentials import Credentials, save
from armarius_mcp.logging_setup import get_logger

log = get_logger(__name__)


class ServerState:
    """Holds the config + client and knows how to persist a freshly minted token."""

    def __init__(self, config: Config, client: ArmariusClient) -> None:
        self.config = config
        self.client = client

    def on_token_minted(self, token: str) -> None:
        """Cache a token from enroll/claim in the client and persist it if we can.

        Persistence uses the credential file path from config when known; otherwise it
        derives the onboarding path from workspace + agent_name (env/creds hints). If we
        lack the identity to name the file, we still keep the token in memory for this
        session (the write is best-effort and never fails a tool call).
        """
        self.client.set_token(token)
        self.config.token = token

        base = self.config.credentials or Credentials()
        creds = Credentials(
            agent_name=self.config.agent_name or base.agent_name,
            agent_role=self.config.agent_role or base.agent_role,
            agent_token=token,
            workspace=self.config.workspace or base.workspace,
            project=self.config.project or base.project,
            api_base_url=self.config.base_url or base.api_base_url,
        )
        self.config.credentials = creds

        path = self.config.credential_path
        if path is None and not (creds.workspace and creds.agent_name):
            log.warning(
                "token minted but no credential path and no workspace/agent_name to derive "
                "one; keeping the token in memory only for this session"
            )
            return
        try:
            written = save(creds, path)
            self.config.credential_path = str(written)
            log.info("saved credentials to %s", written)
        except OSError as exc:
            log.warning("could not persist credentials: %s", exc)
