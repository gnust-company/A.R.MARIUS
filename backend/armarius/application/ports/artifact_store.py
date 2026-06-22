"""Artifact store port — the Shared Artifact Store gateway (§3.4).

A task is only "done" when an output lives here (not on the runtime's local disk).
The local filesystem implementation is the Phase-0 backend; S3/git can follow.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from uuid import UUID


@dataclass(frozen=True)
class StoredObject:
    uri: str
    sha256: str
    size_bytes: int


class ArtifactStore(ABC):
    @abstractmethod
    async def save_bytes(self, project_id: UUID, name: str, data: bytes) -> StoredObject:
        """Persist raw bytes under the project namespace and return a store reference."""
