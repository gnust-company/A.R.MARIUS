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

    async def ensure_ready(self) -> None:  # noqa: B027 — optional hook, default no-op
        """Provision whatever the store needs (a directory, a bucket). Default: no-op."""

    async def healthy(self) -> bool:
        """Liveness probe for the store, surfaced on GET /health. Default: True."""
        return True

    async def exists(self, uri: str) -> bool:  # noqa: B027
        """Whether the bytes behind this reference are still there (FR-069).

        Asked at the moment somebody is about to sign for a deliverable, because a
        signature is a claim about a thing that exists. A row in the artifact table is
        not that claim — it says something *was* published, and buckets get pruned,
        volumes get remounted empty, and a task can be closed against a file nobody can
        open. The default is optimistic so a store that cannot answer never blocks a
        signature; a store that *can* answer is expected to override this.
        """
        return True
