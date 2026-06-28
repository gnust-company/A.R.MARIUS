"""Artifact entity — an output published into the Shared Artifact Store (§3.4, LLD §2.11).

Two kinds only (`patch`/`note` dropped):
  - `file` — bytes uploaded to the MinIO bucket `armarius`; `uri` is the bucket key and
    `stored` is True.
  - `link` — an external URL (e.g. a merged PR); `stored` stays False.
Either kind satisfies the task DONE-gate.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from uuid import UUID, uuid4


class ArtifactKind(StrEnum):
    FILE = "file"
    LINK = "link"


@dataclass
class Artifact:
    id: UUID = field(default_factory=uuid4)
    project_id: UUID | None = None
    task_id: UUID | None = None
    marius_id: UUID | None = None
    name: str = ""
    kind: str = ArtifactKind.FILE  # file | link
    uri: str = ""  # bucket key (file) or external URL (link)
    content_sha256: str | None = None
    size_bytes: int | None = None
    # True ⇒ bytes live in the MinIO bucket `armarius` (file kind only).
    stored: bool = False
    created_at: datetime | None = None
