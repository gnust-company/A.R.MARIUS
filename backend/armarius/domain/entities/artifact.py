"""Artifact entity — an output published into the Shared Artifact Store (§3.4, LLD §2.11).

Two kinds only (`patch`/`note` dropped):
  - `file` — bytes uploaded to the MinIO bucket `armarius`; `uri` is the bucket key.
  - `link` — an external URL (e.g. a merged PR), owned by somewhere else.
Either kind satisfies the task DONE-gate.

The kind is also the answer to "do we own these bytes?", which is what the
acceptance-time existence check needs (FR-069). There used to be a separate `stored`
flag saying the same thing; it had no column behind it, so it read False on every
artifact ever loaded — a field that quietly lied. The API still exposes `stored`, and
derives it from the kind at the edge, which is where it always came from in practice.
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
    created_at: datetime | None = None
