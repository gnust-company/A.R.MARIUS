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
    # Whether the turn happens inside the call that starts it.
    #
    # ``False`` says the work is *handed over*: something else takes it, drives it, and
    # reports the turn's start, its output and its end through its own door. A caller that
    # learns this must not wait for the turn, and must not close the run when the call
    # returns — the run is still owed, by somebody else.
    #
    # This is the one thing about a runtime the orchestration layer genuinely has to know,
    # and it is stated here so that layer can read it off the contract instead of asking
    # *which* runtime this is (Constitution III). A caller that branched on the name would
    # have to be reopened for the next runtime; one that reads this does not.
    turn_ends_in_the_call: bool = True


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

    # How skills get installed is the one instruction that genuinely differs per runtime —
    # a tool call on one, a directory write on another. It lives here, on the contract,
    # rather than as a chain of `if adapter_type == ...` inside a use case: the business
    # layer must not know which runtimes exist (Constitution III, FR-083). An adapter that
    # says nothing gets this neutral wording, which asks the agent to use whatever
    # mechanism its own runtime provides.
    skill_install_steps: tuple[str, ...] = (
        "Install each skill using your runtime's mechanism:",
        "  • Fetch the skill files via the authenticated GET call below",
        "  • Write each file verbatim to your runtime's skills directory",
        "  • Consult your runtime's documentation for the exact skills path",
    )

    @abstractmethod
    async def execute(self, ctx: ExecContext) -> ExecResult:
        """Run exactly one bounded turn against the runtime."""

    async def dispatch(self, ctx: ExecContext) -> ExecResult:
        """Fire one turn at the runtime *without* waiting for it to finish.

        A dispatch succeeds the moment the runtime accepts the work; the agent's turn
        then runs on its own and reports liveness back out-of-band (e.g. ``/agent/me``).
        The default delegates to a full ``execute`` — fine for fast in-process adapters —
        but network adapters override it so a long agent turn never stalls, nor falsely
        fails, the caller (issue #63). Returns a non-terminal status (``RUNNING``) on a
        clean hand-off; ``FAILED`` only if the runtime rejected the work.
        """
        return await self.execute(ctx)

    @abstractmethod
    async def test_environment(self, config: dict) -> Diagnostics:
        """Probe connectivity/auth for a given adapter config."""


class AdapterRegistry(ABC):
    """Resolves an adapter implementation by its `type`."""

    @abstractmethod
    def get(self, adapter_type: str) -> MariusAdapter: ...

    @abstractmethod
    def types(self) -> list[str]: ...
