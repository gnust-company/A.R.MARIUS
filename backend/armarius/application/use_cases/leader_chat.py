"""Chat-with-Leader use case (#82) — a project-level 1-1 conversation with the Leader.

This is the isolated project-scoped counterpart of the task-scoped :class:`WakeEngine`.
It deliberately does NOT touch the task wake path: instead it drives the *same* adapter
streaming primitive directly (``adapter.execute`` + ``ctx.on_event``) against a dedicated
Leader session ``armarius:project:{project_id}:leader`` and tees every event onto the
``leader-chat:{project_id}`` SSE channel. The Leader's reply is reconstructed from the
streamed ``assistant.delta`` events (exactly what the patron sees live) and appended to the
durable transcript — we never ask the agent to call an API to deliver its answer.

Turn-taking: at most one turn per conversation is in flight. While a turn runs the
conversation is ``thinking`` (the API rejects a new message with 409). If the Leader is
offline the chat is disabled entirely (no queue) — offline-ness is computed live from the
Leader's liveness, never persisted.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from uuid import UUID

from armarius.application.ports.adapter import AdapterRegistry, ExecContext
from armarius.application.use_cases.liveness import LivenessEngine
from armarius.application.use_cases.onboarding import credential_file_for
from armarius.application.use_cases.types import UowFactory
from armarius.domain.entities.leader_chat import (
    ChatState,
    LeaderChatError,
    ProjectLeaderConversation,
)
from armarius.domain.entities.marius import Liveness
from armarius.domain.entities.run import RunStatus
from armarius.domain.entities.seat_grant import SeatGrantStatus
from armarius.domain.services.leader_chat_prompt import (
    ChatDirectoryEntry,
    ChatTurn,
    LeaderChatContext,
    build_leader_chat_prompt,
)
from armarius.infrastructure.events.topic_bus import TopicEventBus
from armarius.shared.clock import utcnow
from armarius.shared.logging import get_logger

logger = get_logger(__name__)

# A Leader can take a turn unless it is offline/hung; otherwise the chat is disabled.
_AVAILABLE = {Liveness.ONLINE, Liveness.WORKING, Liveness.IDLE, Liveness.CHECKING}
_LEADER_ROLE_KEY = "leader"
_PROMPT_TURN_TAIL = 10  # recent turns included in the prompt for grounding


@dataclass
class LeaderChatView:
    """What the API surfaces: the conversation plus live, derived context."""

    conversation: ProjectLeaderConversation
    leader_online: bool
    leader_name: str | None
    yolo_mode: bool


class LeaderChatService:
    def __init__(
        self,
        uow_factory: UowFactory,
        *,
        registry: AdapterRegistry,
        control_bus: TopicEventBus,
        liveness: LivenessEngine,
        base_url: str,
        run_timeout_seconds: int = 900,
    ) -> None:
        self._uow = uow_factory
        self._registry = registry
        self._bus = control_bus
        self._liveness = liveness
        self._base_url = base_url
        self._timeout = run_timeout_seconds
        self._bg: set[asyncio.Task[None]] = set()
        self._active: set[UUID] = set()  # conversation ids with an in-flight turn
        self._lock = asyncio.Lock()

    # ── queries ──────────────────────────────────────────────────────────────────
    async def get_or_open(self, project_id: UUID) -> LeaderChatView:
        """Get (or lazily create) the project's Leader conversation and its live context."""
        async with self._uow() as uow:
            project = await uow.projects.get(project_id)
            if project is None:
                raise LookupError("project not found")
            conversation = await uow.leader_chats.get_by_project(project_id)
            leader_id = await self._leader_of(uow, project_id)
            if conversation is None:
                now = utcnow()
                conversation = ProjectLeaderConversation(
                    project_id=project_id,
                    leader_marius_id=leader_id,
                    created_at=now,
                    updated_at=now,
                )
                await uow.leader_chats.add(conversation)
                await uow.commit()
            elif conversation.leader_marius_id != leader_id:
                # Re-resolve the current Leader (the seat may have changed hands).
                conversation.leader_marius_id = leader_id
                conversation.updated_at = utcnow()
                await uow.leader_chats.update(conversation)
                await uow.commit()
            return await self._view(uow, conversation, project)

    # ── send a message ───────────────────────────────────────────────────────────
    async def send(
        self, *, project_id: UUID, message: str
    ) -> LeaderChatView:
        """Append the patron's turn and wake the Leader on the shared project session.

        Raises :class:`LeaderChatError` (→409) if no Leader is seated, the Leader is
        offline (chat disabled), or a turn is already running (turn-taking).
        """
        async with self._uow() as uow:
            project = await uow.projects.get(project_id)
            if project is None:
                raise LookupError("project not found")
            conversation = await uow.leader_chats.get_by_project(project_id)
            leader_id = await self._leader_of(uow, project_id)
            leader = await uow.mariuses.get(leader_id) if leader_id else None
            if leader is None:
                raise LeaderChatError("no Leader is seated on this project")
            if leader.liveness not in _AVAILABLE:
                raise LeaderChatError(
                    "the Leader is offline — the chat is disabled until it comes online"
                )

            now = utcnow()
            if conversation is None:
                conversation = ProjectLeaderConversation(
                    project_id=project_id,
                    leader_marius_id=leader_id,
                    created_at=now,
                    updated_at=now,
                )
                await uow.leader_chats.add(conversation)
            if conversation.state == ChatState.THINKING:
                raise LeaderChatError("the Leader is still replying — wait for its answer")

            conversation.leader_marius_id = leader_id
            conversation.append("patron", message, now)
            conversation.state = ChatState.THINKING
            conversation.updated_at = now
            await uow.leader_chats.update(conversation)
            await uow.commit()
            view = await self._view(uow, conversation, project)

        await self._publish(project_id, "patron.message", {"text": message})
        await self._publish(
            project_id, "chat.state", {"state": str(ChatState.THINKING)}
        )
        self._spawn_turn(conversation.id)
        return view

    # ── the isolated project-scoped turn ─────────────────────────────────────────
    def _spawn_turn(self, conversation_id: UUID) -> None:
        if conversation_id in self._active:
            return
        self._active.add(conversation_id)
        bg = asyncio.create_task(self._run_turn(conversation_id))
        self._bg.add(bg)
        bg.add_done_callback(self._bg.discard)

    async def _run_turn(self, conversation_id: UUID) -> None:
        try:
            await self._do_run_turn(conversation_id)
        except Exception:  # pragma: no cover - defensive; must not strand THINKING
            logger.exception("leader-chat turn %s crashed", conversation_id)
            await self._finish(conversation_id, text="", ok=False, session_params=None)
        finally:
            self._active.discard(conversation_id)

    async def _do_run_turn(self, conversation_id: UUID) -> None:
        async with self._uow() as uow:
            conversation = await uow.leader_chats.get(conversation_id)
            if conversation is None or conversation.project_id is None:
                return
            project = await uow.projects.get(conversation.project_id)
            leader = (
                await uow.mariuses.get(conversation.leader_marius_id)
                if conversation.leader_marius_id
                else None
            )
            if project is None or leader is None:
                await self._finish(conversation_id, text="", ok=False, session_params=None)
                return
            workspace = await uow.workspaces.get(leader.workspace_id)
            directory = await self._team(uow, project.id, leader_id=leader.id)
            project_id = project.id
            adapter_type = leader.adapter_type
            adapter_config = dict(leader.adapter_config)
            yolo = bool(project.settings.get("yolo_mode", False))
            prompt = build_leader_chat_prompt(
                LeaderChatContext(
                    leader_name=leader.name,
                    project_id=project_id,
                    project_name=project.name,
                    workspace_name=workspace.name if workspace else "",
                    project_context=project.context or project.objective,
                    directory=directory,
                    recent_turns=[
                        ChatTurn(role=t.get("role", ""), text=t.get("text", ""))
                        for t in conversation.transcript[-_PROMPT_TURN_TAIL:]
                    ],
                    yolo_mode=yolo,
                    credential_file=(
                        credential_file_for(leader, workspace.name) if workspace else None
                    ),
                )
            )
            session_params = dict(conversation.session_params)
            if not session_params.get("session_id"):
                session_params["session_id"] = f"armarius:project:{project_id}:leader"
                session_params["session_key"] = (
                    f"armarius:agent:{leader.id}:project:{project_id}"
                )

        reply_parts: list[str] = []

        async def on_event(event_type: str, payload: dict) -> None:
            if event_type == "assistant.delta":
                chunk = payload.get("text")
                if chunk:
                    reply_parts.append(str(chunk))
            await self._publish(project_id, event_type, payload)

        ctx = ExecContext(
            prompt=prompt,
            adapter_config=adapter_config,
            session_params=session_params,
            marius_id=leader.id,
            timeout_seconds=self._timeout,
            on_event=on_event,
        )
        adapter = self._registry.get(adapter_type)
        # Mark the Leader WORKING for this turn — a turn counts as liveness, and the watchdog
        # measures silence-since-turn (so an active stream never false-HUNGs). record_signal
        # below clears it again when the turn resolves (#82 liveness loop).
        await self._liveness.begin_turn(leader.id)
        try:
            result = await adapter.execute(ctx)
        except Exception as exc:
            logger.exception("leader-chat adapter execute failed (%s)", conversation_id)
            await self._finish(
                conversation_id, text="", ok=False, session_params=None, error=str(exc)
            )
            return  # liveness left WORKING; the FSM watchdog + gateway probe handle recovery

        await self._finish(
            conversation_id,
            text="".join(reply_parts).strip(),
            ok=result.status == RunStatus.COMPLETED,
            session_params=result.session_params or None,
            error=result.error,
        )
        # The gateway reached back with a terminal status (completed or failed) — fold it in as
        # a liveness signal so a reply keeps the Leader ONLINE and clears the in-flight turn.
        try:
            await self._liveness.record_signal(leader.id)
        except LookupError:  # pragma: no cover — leader vanished mid-turn
            pass

    async def _finish(
        self,
        conversation_id: UUID,
        *,
        text: str,
        ok: bool,
        session_params: dict | None,
        error: str | None = None,
    ) -> None:
        """Append the Leader's reply to the durable transcript and release turn-taking."""
        project_id: UUID | None = None
        state = ChatState.IDLE if ok else ChatState.FAILED
        async with self._uow() as uow:
            conversation = await uow.leader_chats.get(conversation_id)
            if conversation is None:
                return
            project_id = conversation.project_id
            now = utcnow()
            if text:
                conversation.append("leader", text, now)
            if session_params:
                conversation.session_params = session_params
            conversation.state = state
            conversation.updated_at = now
            await uow.leader_chats.update(conversation)
            await uow.commit()

        if project_id is None:
            return
        if text:
            await self._publish(project_id, "leader.message", {"text": text})
        await self._publish(
            project_id,
            "chat.state",
            {"state": str(state), "error": error} if error else {"state": str(state)},
        )

    # ── helpers ──────────────────────────────────────────────────────────────────
    async def _publish(self, project_id: UUID, event_type: str, payload: dict) -> None:
        await self._bus.publish(f"leader-chat:{project_id}", event_type, payload)

    async def _view(
        self, uow, conversation: ProjectLeaderConversation, project  # noqa: ANN001
    ) -> LeaderChatView:
        leader = (
            await uow.mariuses.get(conversation.leader_marius_id)
            if conversation.leader_marius_id
            else None
        )
        return LeaderChatView(
            conversation=conversation,
            leader_online=bool(leader is not None and leader.liveness in _AVAILABLE),
            leader_name=leader.name if leader else None,
            yolo_mode=bool(project.settings.get("yolo_mode", False)),
        )

    async def _leader_of(self, uow, project_id: UUID) -> UUID | None:  # noqa: ANN001
        grants = await uow.seat_grants.list_by_project(project_id)
        leader = next(
            (
                g
                for g in grants
                if g.status == SeatGrantStatus.GRANTED
                and g.role_key == _LEADER_ROLE_KEY
                and g.marius_id is not None
            ),
            None,
        )
        return leader.marius_id if leader else None

    async def _team(
        self, uow, project_id: UUID, *, leader_id: UUID  # noqa: ANN001
    ) -> list[ChatDirectoryEntry]:
        grants = await uow.seat_grants.list_by_project(project_id)
        entries: list[ChatDirectoryEntry] = []
        seen: set[UUID] = set()
        for g in grants:
            if (
                g.status != SeatGrantStatus.GRANTED
                or g.role_key == _LEADER_ROLE_KEY
                or g.marius_id is None
                or g.marius_id == leader_id
                or g.marius_id in seen
            ):
                continue
            seen.add(g.marius_id)
            worker = await uow.mariuses.get(g.marius_id)
            if worker is not None:
                entries.append(
                    ChatDirectoryEntry(
                        marius_id=worker.id,
                        name=worker.name,
                        role=worker.role,
                        liveness=str(worker.liveness),
                    )
                )
        return entries
