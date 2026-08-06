"""MinIO (S3-compatible) Shared Artifact Store — the production backend (ARCHITECTURE §7).

Objects land under the bucket `armarius` keyed `<project_id>/<sha-prefixed-name>` (the richer
`<project-slug>/<task>/<name>` layout arrives with rich artifacts in a later sprint). The MinIO
SDK is synchronous, so every blocking call is run in a worker thread via `asyncio.to_thread`
to keep the event loop free.
"""

from __future__ import annotations

import asyncio
import hashlib
import io
import re
from uuid import UUID

from minio import Minio

from armarius.application.ports.artifact_store import ArtifactStore, StoredObject

_SAFE = re.compile(r"[^A-Za-z0-9._-]+")


class MinioArtifactStore(ArtifactStore):
    def __init__(
        self,
        *,
        endpoint: str,
        access_key: str,
        secret_key: str,
        bucket: str,
        secure: bool = False,
    ) -> None:
        self._bucket = bucket
        self._client = Minio(
            endpoint, access_key=access_key, secret_key=secret_key, secure=secure
        )

    async def ensure_ready(self, *, retries: int = 10, delay: float = 1.0) -> None:
        def _make() -> None:
            if not self._client.bucket_exists(self._bucket):
                self._client.make_bucket(self._bucket)

        # MinIO may still be starting (we depend on it with service_started, not a
        # healthcheck), so retry the bucket provisioning a few times before giving up.
        last: Exception | None = None
        for _ in range(retries):
            try:
                await asyncio.to_thread(_make)
                return
            except Exception as exc:  # noqa: BLE001 — surface only after all retries
                last = exc
                await asyncio.sleep(delay)
        if last is not None:
            raise last

    async def healthy(self) -> bool:
        try:
            return bool(await asyncio.to_thread(self._client.bucket_exists, self._bucket))
        except Exception:
            return False

    async def save_bytes(self, project_id: UUID, name: str, data: bytes) -> StoredObject:
        sha = hashlib.sha256(data).hexdigest()
        safe_name = _SAFE.sub("_", name) or "artifact"
        key = f"{project_id}/{sha[:12]}-{safe_name}"

        def _put() -> None:
            self._client.put_object(
                self._bucket,
                key,
                io.BytesIO(data),
                length=len(data),
                content_type="application/octet-stream",
            )

        await asyncio.to_thread(_put)
        return StoredObject(uri=key, sha256=sha, size_bytes=len(data))

    async def exists(self, uri: str) -> bool:
        """Whether the object behind this key is still in the bucket (FR-069).

        A failure to reach MinIO answers **True**, not False. The question being asked is
        "has this deliverable been lost?", and a network blip is not evidence of loss — an
        outage that answered False would send every task in review back for rework and
        undo a day's signatures over something that fixed itself in a minute.
        """
        if not uri:
            return False

        def _stat() -> bool:
            try:
                self._client.stat_object(self._bucket, uri)
                return True
            except Exception as exc:  # noqa: BLE001 - the SDK raises S3Error for both cases
                return "NoSuchKey" not in str(exc) and "not exist" not in str(exc).lower()

        try:
            return bool(await asyncio.to_thread(_stat))
        except Exception:  # pragma: no cover - unreachable store is not proof of loss
            return True
