"""Logging for a stdio MCP server.

stdout is the JSON-RPC transport — a single stray byte there corrupts the protocol.
So every log record goes to **stderr**, and nothing in this package ever prints to
stdout. Call ``configure_logging()`` once at startup.
"""

from __future__ import annotations

import logging
import os
import sys

_CONFIGURED = False


def configure_logging() -> None:
    """Route all logging to stderr. Idempotent."""
    global _CONFIGURED
    if _CONFIGURED:
        return
    level = os.environ.get("ARMARIUS_MCP_LOG_LEVEL", "INFO").upper()
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    )
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(getattr(logging, level, logging.INFO))
    _CONFIGURED = True


def get_logger(name: str = "armarius_mcp") -> logging.Logger:
    return logging.getLogger(name)
