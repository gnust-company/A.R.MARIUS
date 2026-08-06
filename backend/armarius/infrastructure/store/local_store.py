"""Local filesystem Shared Artifact Store (§3.4).

Files land under ARTIFACT_STORE_ROOT/<project_id>/<sha-prefixed-name>. Swap this
implementation for S3/git later without touching the application layer.
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path
from uuid import UUID

from armarius.application.ports.artifact_store import ArtifactStore, StoredObject

_SAFE = re.compile(r"[^A-Za-z0-9._-]+")


class LocalArtifactStore(ArtifactStore):
    def __init__(self, root: Path) -> None:
        self._root = root

    async def ensure_ready(self) -> None:
        self._root.mkdir(parents=True, exist_ok=True)

    async def save_bytes(self, project_id: UUID, name: str, data: bytes) -> StoredObject:
        sha = hashlib.sha256(data).hexdigest()
        safe_name = _SAFE.sub("_", name) or "artifact"
        rel = Path(str(project_id)) / f"{sha[:12]}-{safe_name}"
        dest = self._root / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(data)
        return StoredObject(uri=str(rel), sha256=sha, size_bytes=len(data))

    async def exists(self, uri: str) -> bool:
        """Whether the file behind this key is still on disk (FR-069).

        A path that escapes the root answers *no* rather than reaching outside it: a
        reference that walks out of the store is not a stored artifact by definition, and
        following it would let a stray `..` make the store report on the host filesystem.
        """
        if not uri:
            return False
        candidate = (self._root / uri).resolve()
        root = self._root.resolve()
        if not candidate.is_relative_to(root):
            return False
        return candidate.is_file()
