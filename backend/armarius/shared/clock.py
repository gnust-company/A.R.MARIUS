"""Time helpers — single source of 'now' so the domain stays testable."""

from __future__ import annotations

from datetime import UTC, datetime


def utcnow() -> datetime:
    """Timezone-aware UTC now."""
    return datetime.now(UTC)
