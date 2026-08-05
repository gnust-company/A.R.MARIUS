"""Time helpers — single source of 'now' so the domain stays testable."""

from __future__ import annotations

from datetime import UTC, datetime


def utcnow() -> datetime:
    """Timezone-aware UTC now."""
    return datetime.now(UTC)


def as_utc(value: datetime | None) -> datetime | None:
    """Read a stored timestamp back as timezone-aware UTC.

    Columns are declared ``DateTime(timezone=True)``, which PostgreSQL honours and SQLite
    does not: the same row comes back aware in production and **naive** in the test and
    local-dev database. Any arithmetic mixing the two raises, so a rule that compares a
    stored timestamp against `utcnow()` works on one engine and blows up on the other.

    Normalising on read — here, at the boundary — keeps that difference out of the domain
    rules, which are entitled to assume every datetime they are handed is aware.
    """
    if value is None:
        return None
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)
