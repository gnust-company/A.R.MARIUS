"""Artifact entity — an output published into the Shared Artifact Store (§3.4)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from uuid import UUID, uuid4


@dataclass
class Artifact:
    id: UUID = field(default_factory=uuid4)
    project_id: UUID | None = None
    task_id: UUID | None = None
    marius_id: UUID | None = None
    name: str = ""
    kind: str = "file"  # file | patch | link | note
    uri: str = ""  # store-relative path or external URL
    content_sha256: str | None = None
    size_bytes: int | None = None
    created_at: datetime | None = None
