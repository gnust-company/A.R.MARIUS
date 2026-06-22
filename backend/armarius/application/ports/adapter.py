"""MariusAdapter port — the bounded `execute()` contract every runtime is wrapped in.

Generalised from Paperclip (§5.4). A wake = one bounded turn: the wake engine calls
`execute(ctx)`, the adapter drives the runtime, tees streaming events through
`ctx.on_event`, and returns an `ExecResult` carrying the (possibly new) native
session handle so the next wake on the same task can resume.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from uuid import UUID

from armarius.domain.entities.run import RunStatus

# Called by the adapter for each streamed runtime event (type, payload).
EventCallback = Callable[[str, dict], Awaitable[None]]


@dataclass(frozen=True)
class AdapterCapabilities:
    resumable: bool
    streaming: bool
    transport: str  # "process" | "http" | "webhook" | "ws"


@dataclass
class ExecContext:
    """Everything an adapter needs to run one bounded turn."""

    prompt: str
    adapter_config: dict
    session_params: dict = field(default_factory=dict)  # existing native handle (may be empty)
    marius_id: UUID | None = None
    task_id: UUID | None = None
    run_id: UUID | None = None
    timeout_seconds: int = 900
    on_event: EventCallback | None = None


@dataclass
class ExecResult:
    status: RunStatus
    session_params: dict = field(default_factory=dict)
    session_display_id: str | None = None
    external_run_id: str | None = None
    usage: dict = field(default_factory=dict)
    error: str | None = None
    next_action: str | None = None


@dataclass
class Diagnostics:
    ok: bool
    detail: str = ""
    info: dict = field(default_factory=dict)


class MariusAdapter(ABC):
    """A pluggable bridge between Armarius orchestration and a concrete runtime."""

    type: str
    capabilities: AdapterCapabilities

    @abstractmethod
    async def execute(self, ctx: ExecContext) -> ExecResult:
        """Run exactly one bounded turn against the runtime."""

    @abstractmethod
    async def test_environment(self, config: dict) -> Diagnostics:
        """Probe connectivity/auth for a given adapter config."""


class AdapterRegistry(ABC):
    """Resolves an adapter implementation by its `type`."""

    @abstractmethod
    def get(self, adapter_type: str) -> MariusAdapter: ...

    @abstractmethod
    def types(self) -> list[str]: ...
