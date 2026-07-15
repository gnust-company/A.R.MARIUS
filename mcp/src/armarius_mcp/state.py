"""Server state: the resolved config + the HTTP client.

Kept separate from ``server.py`` so the tool implementations in ``tools.py`` can be
driven with a fake ``ArmariusClient`` in unit tests (constructor injection).
"""

from __future__ import annotations

from armarius_mcp.client import ArmariusClient
from armarius_mcp.config import Config


class ServerState:
    """Holds the config + client. The token is resolved at startup (config.py); tools
    just use it."""

    def __init__(self, config: Config, client: ArmariusClient) -> None:
        self.config = config
        self.client = client
