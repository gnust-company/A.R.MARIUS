"""Shared application-layer type aliases."""

from __future__ import annotations

from collections.abc import Callable

from armarius.application.ports.unit_of_work import UnitOfWork

# A factory that opens a fresh Unit of Work (transactional boundary) per operation.
UowFactory = Callable[[], UnitOfWork]
