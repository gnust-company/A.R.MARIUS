"""The patron talking to one of their agents directly (FR-007p).

The sibling of the project chat (``LeaderChatService``) with the project taken out: one
conversation per agent, one turn in flight at a time, the reply streamed while it is written
and kept in the transcript once it is done. An agent that cannot be reached cannot be written
to — the box is disabled rather than queued, the same rule the project chat follows.

A turn is a run like any other. It is taken wherever the agent works, it shows in the agent's
activity, and it ends by the same roads every run ends by. What it carries is written down with
it when the patron writes (FR-040c): there is no task to re-read for anything fresher.

Constitution III holds here the way it holds in the project chat: whether a turn ends inside
the call or somewhere else is asked of the adapter's contract, never of its name.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from uuid import UUID

from armarius.application.ports.adapter import AdapterRegistry, ExecContext, MariusAdapter
from armarius.application.use_cases.liveness import LivenessEngine
from armarius.application.use_cases.run_reply import SAID, said_in
from armarius.application.use_cases.types import UowFactory
from armarius.domain.entities.agent_chat import AgentChatError, AgentConversation
from armarius.domain.entities.leader_chat import ChatState
from armarius.domain.entities.marius import Liveness, Marius
from armarius.domain.entities.run import ACTIVE_RUN_STATUSES, Run, RunStatus, WakeSource
from armarius.domain.entities.wakeup import WakeupRequest, WakeupStatus
from armarius.domain.services.agent_chat_prompt import (
    TURN_TAIL,
    AgentChatContext,
    build_agent_chat_prompt,
)
from armarius.domain.services.leader_chat_prompt import ChatTurn
from armarius.domain.services.wake_reason import reason
from armarius.infrastructure.events.topic_bus import TopicEventBus
from armarius.shared.background import settle
from armarius.shared.clock import utcnow
from armarius.shared.errors import NotFound
from armarius.shared.logging import get_logger

logger = get_logger(__name__)

RunCloser = Callable[..., Awaitable[None]]

# Who can take a turn. The same set the project chat uses: CHECKING is an agent being asked
# whether it is still there, not one known to be gone.
_AVAILABLE = {Liveness.ONLINE, Liveness.WORKING, Liveness.CHECKING}

# The one cause this conversation has: the patron wrote. Stored as a code so the activity log
# reads it in the patron's language and the agent in English (Constitution VII).
_CAUSE = reason("agent_chat_message")


@dataclass
class AgentChatView:
    """The conversation as the screen needs it, plus what is only true right now."""

    transcript: list[dict]
    state: ChatState
    agent_online: bool


class AgentChatService:
    def __init__(
        self,
        uow_factory: UowFactory,
        *,
        registry: AdapterRegistry,
        control_bus: TopicEventBus,
        liveness: LivenessEngine,
        run_timeout_seconds: int = 900,
        close_run: RunCloser | None = None,
    ) -> None:
        self._uow = uow_factory
        self._registry = registry
        self._bus = control_bus
        self._liveness = liveness
        self._timeout = run_timeout_seconds
        self._close_run = close_run
        self._bg: set[asyncio.Task[None]] = set()
        self._active: set[UUID] = set()
        # Runs handed elsewhere, and the agent whose conversation is waiting on each. Held in
        # memory for the reason the project chat gives: the door that reports events reports
        # every run's events, and a read per event to answer "not mine" is not worth it. A
        # restart loses this turn's live typing and nothing else — the reply is rebuilt from
        # the record when the run ends.
        self._watching: dict[UUID, UUID] = {}

    # ── reads ────────────────────────────────────────────────────────────────────
    async def view(self, marius_id: UUID) -> AgentChatView:
        """The conversation with this agent. Reading it never creates it: a write on a read
        path would make opening an agent's page a thing that changes the database."""
        async with self._uow() as uow:
            agent = await uow.mariuses.get(marius_id)
            if agent is None:
                raise NotFound("agent_not_found")
            conversation = await uow.agent_chats.get_by_agent(marius_id)
        return _view_of(conversation, agent)

    # ── the patron writes ────────────────────────────────────────────────────────
    async def send(self, marius_id: UUID, message: str) -> AgentChatView:
        """Append the patron's message and start the agent's turn.

        Raises ``AgentChatError`` (→ 409) when the agent cannot be reached or is still
        answering the last message.
        """
        text = message.strip()
        if not text:
            raise AgentChatError("agent_chat_empty_message")
        async with self._uow() as uow:
            agent = await uow.mariuses.get(marius_id)
            if agent is None:
                raise NotFound("agent_not_found")
            if agent.liveness not in _AVAILABLE:
                raise AgentChatError("agent_offline")
            now = utcnow()
            conversation = await uow.agent_chats.get_by_agent(marius_id)
            if conversation is None:
                conversation = AgentConversation(
                    marius_id=marius_id, created_at=now, updated_at=now
                )
                await uow.agent_chats.add(conversation)
            if conversation.state == ChatState.THINKING:
                raise AgentChatError("agent_still_replying")
            conversation.append("patron", text, now)
            conversation.state = ChatState.THINKING
            conversation.updated_at = now
            await uow.agent_chats.update(conversation)
            await uow.commit()
            view = _view_of(conversation, agent)

        await self._publish(marius_id, "patron.message", {"text": text})
        await self._publish(marius_id, "chat.state", {"state": str(ChatState.THINKING)})
        self._spawn_turn(conversation.id)
        return view

    # ── the agent's turn ─────────────────────────────────────────────────────────
    def _spawn_turn(self, conversation_id: UUID) -> None:
        if conversation_id in self._active:
            return
        self._active.add(conversation_id)
        task = asyncio.create_task(self._run_turn(conversation_id))
        self._bg.add(task)
        task.add_done_callback(self._bg.discard)

    async def _run_turn(self, conversation_id: UUID) -> None:
        try:
            await self._take_turn(conversation_id)
        except Exception:  # pragma: no cover - defensive; must not strand THINKING
            logger.exception("agent-chat turn %s crashed", conversation_id)
            # A conversation left thinking refuses the patron's every next message, with
            # nothing on screen to say why — see the project chat, which learned this first.
            await settle(
                f"close the stranded agent-chat turn {conversation_id}",
                lambda: self._finish(conversation_id, text="", ok=False),
            )
        finally:
            self._active.discard(conversation_id)

    async def _take_turn(self, conversation_id: UUID) -> None:
        async with self._uow() as uow:
            conversation = await uow.agent_chats.get(conversation_id)
            if conversation is None or conversation.marius_id is None:
                return
            agent = await uow.mariuses.get(conversation.marius_id)
            if agent is None:
                await self._finish(conversation_id, text="", ok=False)
                return
            workspace = await uow.workspaces.get(agent.workspace_id)
            tail = list(conversation.transcript[-TURN_TAIL:])

        latest = tail.pop() if tail and tail[-1].get("role") == "patron" else None
        if latest is None:  # pragma: no cover - a turn is only ever started by a message
            await self._finish(conversation_id, text="", ok=False)
            return
        prompt = build_agent_chat_prompt(
            AgentChatContext(
                agent_name=agent.name,
                workspace_name=workspace.name if workspace else "",
                instructions=agent.instructions,
                system_instructions=agent.system_instructions,
                history=[
                    ChatTurn(role=str(t.get("role", "")), text=str(t.get("text", "")))
                    for t in tail
                ],
                message=str(latest.get("text", "")),
            )
        )

        adapter = self._registry.get(agent.adapter_type)
        if not adapter.capabilities.turn_ends_in_the_call:
            await self._hand_over(conversation_id, adapter, agent=agent, prompt=prompt)
            return

        reply_parts: list[str] = []

        async def on_event(event_type: str, payload: dict) -> None:
            if event_type == "assistant.delta":
                chunk = payload.get("text")
                if chunk:
                    reply_parts.append(str(chunk))
            await self._publish(agent.id, event_type, payload)

        await self._liveness.begin_turn(agent.id)
        try:
            result = await adapter.execute(
                ExecContext(
                    prompt=prompt,
                    adapter_config=dict(agent.adapter_config or {}),
                    session_params={},
                    marius_id=agent.id,
                    timeout_seconds=self._timeout,
                    on_event=on_event,
                )
            )
        except Exception as exc:
            logger.exception("agent-chat turn %s failed in the adapter", conversation_id)
            await self._finish(conversation_id, text="", ok=False, error=str(exc))
            return
        ok = result.status == RunStatus.COMPLETED
        await self._finish(
            conversation_id,
            text="".join(reply_parts).strip(),
            ok=ok,
            error=None if ok else result.error,
        )
        # Only an answer is contact. A failed attempt to reach an agent must never be the
        # thing that marks it alive — the project chat once kept a dead Leader online that way.
        if ok:
            await self._signal(agent.id)

    async def _hand_over(
        self, conversation_id: UUID, adapter: MariusAdapter, *, agent: Marius, prompt: str
    ) -> None:
        """Offer the turn to wherever the agent works, and let go (FR-040b, FR-040e).

        The conversation stays thinking and the run stays queued until it is taken; what
        comes back from the offer says only whether it was accepted.
        """
        now = utcnow()
        run = Run(
            marius_id=agent.id,
            adapter_type=agent.adapter_type,
            # Somebody asked for this, here and now. Not a cause of its own for the same
            # reason the interview gives: the closed lists of FR-048a say who may wake a
            # Leader or a worker, and an agent answering its patron is wearing neither hat.
            wake_source=WakeSource.ON_DEMAND,
            trigger_causes=[_CAUSE],
            trigger_detail=_CAUSE.render_en(),
            status=RunStatus.QUEUED,
            created_at=now,
        )
        async with self._uow() as uow:
            conversation = await uow.agent_chats.get(conversation_id)
            if conversation is None:  # pragma: no cover - read moments ago
                return
            conversation.driving_run_id = run.id
            conversation.updated_at = now
            await uow.agent_chats.update(conversation)
            await uow.runs.add(run)
            await uow.wakeups.add(
                WakeupRequest(
                    marius_id=agent.id,
                    source=run.wake_source,
                    causes=[_CAUSE],
                    reason=_CAUSE.render_en(),
                    prompt=prompt,
                    status=WakeupStatus.DISPATCHED,
                    run_id=run.id,
                    created_at=now,
                )
            )
            await uow.commit()

        self._watching[run.id] = agent.id
        try:
            result = await adapter.dispatch(
                ExecContext(
                    prompt=prompt,
                    adapter_config=dict(agent.adapter_config or {}),
                    marius_id=agent.id,
                    run_id=run.id,
                    timeout_seconds=self._timeout,
                )
            )
        except Exception as exc:
            logger.exception("agent-chat turn %s could not be handed over", conversation_id)
            await self._not_taken(conversation_id, run.id, RunStatus.FAILED, str(exc))
            return
        if result.status in ACTIVE_RUN_STATUSES:
            return
        # Refused at the door. Nothing is coming for this run, so it ends here, and the
        # conversation is released with it rather than left thinking behind a dead run.
        await self._not_taken(conversation_id, run.id, result.status, result.error)

    async def _not_taken(
        self, conversation_id: UUID, run_id: UUID, status: RunStatus, error: str | None
    ) -> None:
        self._watching.pop(run_id, None)
        if self._close_run is not None:
            await self._close_run(run_id, status=status, error=error)
        await self._finish(conversation_id, text="", ok=False, error=error)

    # ── news from runs taken elsewhere ───────────────────────────────────────────
    async def run_event(self, run_id: UUID, event_type: str, payload: dict) -> None:
        """Show what the agent is saying, if a conversation is waiting on this run.

        Called for every run's every event, so it answers "not mine" from memory first.
        """
        marius_id = self._watching.get(run_id)
        if marius_id is None or event_type != SAID:
            return
        text = payload.get("text")
        if text:
            await self._publish(marius_id, "assistant.delta", {"text": str(text)})

    async def run_ended(self, run_id: UUID) -> None:
        """A run is over — if it was carrying a turn of some conversation, so is the turn.

        The reply is read back from the record rather than from anything held here, which is
        what lets the ending survive a restart.
        """
        async with self._uow() as uow:
            conversation = await uow.agent_chats.get_by_run(run_id)
            if conversation is None:
                return
            run = await uow.runs.get(run_id)
            ok = run is not None and run.status == RunStatus.COMPLETED
            text = await said_in(uow, run_id) if ok else ""
            error = None if ok else (run.error if run is not None else None)
            conversation_id = conversation.id
            marius_id = conversation.marius_id
        self._watching.pop(run_id, None)
        await self._finish(conversation_id, text=text, ok=ok, error=error)
        if ok and marius_id is not None:
            await self._signal(marius_id)

    # ── endings ──────────────────────────────────────────────────────────────────
    async def _finish(
        self, conversation_id: UUID, *, text: str, ok: bool, error: str | None = None
    ) -> None:
        """Keep the reply and release turn-taking."""
        state = ChatState.IDLE if ok else ChatState.FAILED
        async with self._uow() as uow:
            conversation = await uow.agent_chats.get(conversation_id)
            if conversation is None or conversation.marius_id is None:
                return
            marius_id = conversation.marius_id
            now = utcnow()
            if text:
                conversation.append("agent", text, now)
            conversation.state = state
            conversation.driving_run_id = None
            conversation.updated_at = now
            await uow.agent_chats.update(conversation)
            await uow.commit()
        if text:
            await self._publish(marius_id, "agent.message", {"text": text})
        payload: dict = {"state": str(state)}
        if error:
            payload["error"] = error
        await self._publish(marius_id, "chat.state", payload)

    async def _signal(self, marius_id: UUID) -> None:
        try:
            await self._liveness.record_signal(marius_id)
        except LookupError:  # pragma: no cover - agent removed mid-turn
            pass

    async def _publish(self, marius_id: UUID, event_type: str, payload: dict) -> None:
        await self._bus.publish(f"agent-chat:{marius_id}", event_type, payload)


def _view_of(conversation: AgentConversation | None, agent: Marius) -> AgentChatView:
    return AgentChatView(
        transcript=list(conversation.transcript) if conversation else [],
        state=conversation.state if conversation else ChatState.IDLE,
        agent_online=agent.liveness in _AVAILABLE,
    )
