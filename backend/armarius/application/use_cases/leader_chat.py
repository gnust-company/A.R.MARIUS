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
from armarius.application.ports.unit_of_work import UnitOfWork
from armarius.application.use_cases.liveness import LivenessEngine
from armarius.application.use_cases.onboarding import credential_file_for
from armarius.application.use_cases.seats import (
    leader_marius_id,
    leader_role_ids,
)
from armarius.application.use_cases.seats import (
    leader_role as leader_role_of,
)
from armarius.application.use_cases.types import UowFactory
from armarius.domain.entities.leader_chat import (
    ChatState,
    LeaderChatError,
    ProjectLeaderConversation,
)
from armarius.domain.entities.marius import Liveness
from armarius.domain.entities.run import RunStatus, WakeSource
from armarius.domain.entities.wakeup import WakeupRequest, WakeupStatus
from armarius.domain.services.leader_chat_prompt import (
    ChatDirectoryEntry,
    ChatTurn,
    LeaderChatContext,
    PlanScopeEntry,
    build_leader_chat_prompt,
)
from armarius.domain.services.wake_policy import WakeRole, may_wake
from armarius.domain.services.wake_prompt import ProjectBrief
from armarius.domain.services.wake_reason import WakeReason
from armarius.infrastructure.events.topic_bus import TopicEventBus
from armarius.shared.background import settle
from armarius.shared.clock import utcnow
from armarius.shared.errors import NotFound
from armarius.shared.logging import get_logger

logger = get_logger(__name__)

# A Leader can take a turn unless it is offline/hung; otherwise the chat is disabled.
_AVAILABLE = {Liveness.ONLINE, Liveness.WORKING, Liveness.CHECKING}
_PROMPT_TURN_TAIL = 10  # recent turns included in the prompt for grounding


@dataclass
class LeaderChatView:
    """What the API surfaces: the conversation plus live, derived context."""

    conversation: ProjectLeaderConversation
    leader_online: bool
    leader_name: str | None


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
                raise NotFound("project_not_found")
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
                raise NotFound("project_not_found")
            conversation = await uow.leader_chats.get_by_project(project_id)
            leader_id = await self._leader_of(uow, project_id)
            leader = await uow.mariuses.get(leader_id) if leader_id else None
            if leader is None:
                raise LeaderChatError("no_leader_seated")
            if leader.liveness not in _AVAILABLE:
                raise LeaderChatError("leader_offline")

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
                raise LeaderChatError("leader_still_replying")

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

    # ── system-initiated wake (spec 001) ─────────────────────────────────────────
    async def notify(
        self,
        *,
        project_id: UUID,
        source: WakeSource,
        reason: WakeReason,
        detail: str = "",
    ) -> bool:
        """Wake the Leader about the **project** — no task involved (FR-002, FR-013).

        Story-1 wakes are project-level: "the roster filled up, go clarify the context and
        plan", "the patron approved, go split the work". They ride the same shared project
        session the Chat-with-Leader tab uses, so the Leader keeps one continuous thread
        about its project instead of waking cold.

        Always records a durable `WakeupRequest` so the wake is auditable even when it
        cannot be delivered. Returns True if the Leader was actually woken; False when it
        is offline or already mid-turn — the phase change still stands, and the pending
        reason is on the record for the orchestration cadence to pick up.

        This is the second of the two doors a wake leaves by, and the cause list is checked
        at both (FR-048a). Everything arriving here is addressed to the Leader by
        construction, so the question is simply whether the Leader may be woken for this
        cause at all. The patron's own turn in the chat tab does not come through here: it
        goes straight to `send`, which is the one cause — the patron writing — that needs
        no test.

        Callers hand over a **cause**, never a sentence. What the Leader ends up reading is
        the four-part core of its own chat prompt (role, brief, why it is awake, who else is
        here — FR-044) plus `detail`, the extra this particular call type owes it (FR-044a).
        `detail` is the agent's copy and therefore English; the cause is stored as code and
        parameters so the patron, who watches the very same conversation, reads it in their
        own language (Constitution VII).
        """
        async with self._uow() as uow:
            project = await uow.projects.get(project_id)
            if project is None:
                raise NotFound("project_not_found")
            if not may_wake(source, roles={WakeRole.LEADER}):
                await self._record_refusal(uow, project_id, source, reason)
                return False
            conversation = await uow.leader_chats.get_by_project(project_id)
            leader_id = await self._leader_of(uow, project_id)
            leader = await uow.mariuses.get(leader_id) if leader_id else None

            now = utcnow()
            # The agent's copy of the packet body: the cause, then whatever this call type
            # owes on top of it.
            body = reason.render_en()
            if detail.strip():
                body = f"{body}\n\n{detail.strip()}" if body else detail.strip()
            deliverable = (
                leader is not None
                and leader.liveness in _AVAILABLE
                and (conversation is None or conversation.state != ChatState.THINKING)
            )
            await uow.wakeups.add(
                WakeupRequest(
                    project_id=project_id,
                    marius_id=leader_id,
                    task_id=None,
                    source=source,
                    causes=[reason],
                    reason=reason.render_en(),
                    prompt=body,
                    status=WakeupStatus.DISPATCHED if deliverable else WakeupStatus.QUEUED,
                    created_at=now,
                )
            )
            if not deliverable:
                await uow.commit()
                logger.info(
                    "project wake %s queued for project %s (leader unavailable)",
                    source,
                    project_id,
                )
                return False

            if conversation is None:
                conversation = ProjectLeaderConversation(
                    project_id=project_id,
                    leader_marius_id=leader_id,
                    created_at=now,
                    updated_at=now,
                )
                await uow.leader_chats.add(conversation)
            conversation.leader_marius_id = leader_id
            conversation.append_system(
                code=reason.code,
                params=dict(reason.params),
                text=reason.render_en(),
                detail=detail.strip(),
                ts=now,
            )
            conversation.state = ChatState.THINKING
            conversation.updated_at = now
            await uow.leader_chats.update(conversation)
            await uow.commit()

        await self._publish(
            project_id,
            "system.message",
            {"code": reason.code, "params": dict(reason.params), "text": body},
        )
        await self._publish(project_id, "chat.state", {"state": str(ChatState.THINKING)})
        self._spawn_turn(conversation.id)
        return True

    async def _record_refusal(
        self, uow: UnitOfWork, project_id: UUID, source: WakeSource, reason: WakeReason
    ) -> None:
        """Write down a wake the Leader's list does not allow, then drop it (FR-048a)."""
        logger.warning(
            "wake refused: %s may not wake the Leader of project %s", source, project_id
        )
        await uow.wakeups.add(
            WakeupRequest(
                project_id=project_id,
                marius_id=await self._leader_of(uow, project_id),
                task_id=None,
                source=source,
                causes=[reason],
                reason=reason.render_en(),
                status=WakeupStatus.REFUSED,
                created_at=utcnow(),
            )
        )
        await uow.commit()

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
            # Closing the turn is itself a write, and a write can be refused. Attempted once
            # and lost, the exception would leave this background task for nobody, and the
            # conversation would sit in *thinking* with nothing behind it — the API rejects
            # every new message with 409, so the patron is locked out of their own chat with
            # no error anywhere to explain it.
            await settle(
                f"close the stranded leader-chat turn {conversation_id}",
                lambda: self._finish(
                    conversation_id, text="", ok=False, session_params=None
                ),
            )
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
            # The Leader's own project role, for the prompt header (its duties/description).
            leader_role = await leader_role_of(uow, project.id)
            project_id = project.id
            adapter_type = leader.adapter_type
            adapter_config = dict(leader.adapter_config)
            # What the patron already signed off (FR-027) — the Leader needs the item ids
            # to attach work to, otherwise everything it creates lands as a scope change.
            approved_plan = await uow.plans.get_approved(project.id)
            plan_items = [
                PlanScopeEntry(item_id=i.id, title=i.title)
                for i in (approved_plan.items if approved_plan else [])
            ]
            # FR-009: the brief in force, same as every worker's packet. Reading
            # `project.context`/`project.objective` instead — two raw columns that pass
            # through no gate — meant the patron could revise the brief and have it
            # approved, workers would read the new version, and the Leader would keep
            # arguing from the old one.
            approved_brief = await uow.project_contexts.get_approved(project.id)
            brief = (
                ProjectBrief(
                    objective=approved_brief.objective,
                    background=approved_brief.background,
                    constraints=approved_brief.constraints,
                    scope=approved_brief.scope,
                    principles=approved_brief.principles,
                )
                if approved_brief is not None
                else None
            )
            tail = list(conversation.transcript[-_PROMPT_TURN_TAIL:])
            # A wake that opened this turn is the packet's *why you were woken* (FR-044),
            # not one more line of chat history. It is lifted out of the tail so it is said
            # once, in the part built to say it — and so its extra (FR-044a) rides along
            # instead of being flattened into a quote of something nobody said.
            opening_wake = (
                tail.pop() if tail and tail[-1].get("role") == "system" else None
            )
            prompt = build_leader_chat_prompt(
                LeaderChatContext(
                    leader_name=leader.name,
                    project_id=project_id,
                    project_name=project.name,
                    workspace_name=workspace.name if workspace else "",
                    project_brief=brief,
                    commission=project.context or project.objective or "",
                    directory=directory,
                    recent_turns=[
                        ChatTurn(role=str(t.get("role", "")), text=str(t.get("text", "")))
                        for t in tail
                    ],
                    wake_reason=(
                        str(opening_wake.get("text", "")) if opening_wake else ""
                    ),
                    wake_detail=(
                        str(opening_wake.get("detail", "")) if opening_wake else ""
                    ),
                    plan_items=plan_items,
                    leader_role_description=(
                        leader_role.description if leader_role else ""
                    ),
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
        # A **completed** turn is contact: the Leader answered, so it is alive. A failed one
        # is not, and folding it in as one used to break FR-064 outright.
        #
        # The adapter reports an unreachable gateway by *returning* FAILED rather than
        # raising, so this line used to mark a Leader ONLINE precisely because the attempt
        # to talk to it had failed. On a running service that made the state unreachable:
        # anything that kept waking a dead Leader — a stall escalation, a cadence sweep —
        # kept resetting it to ONLINE, so it could never decay to OFFLINE, so the patron was
        # never told their project had lost its manager. Watched it happen.
        #
        # On failure liveness is left exactly as the exception path above leaves it: alone,
        # for the FSM watchdog and the gateway probe to decide. Those two ask the gateway
        # instead of asking our own outbound attempt, which is the only honest source.
        if result.status is not RunStatus.COMPLETED:
            return
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
        )

    async def _leader_of(self, uow, project_id: UUID) -> UUID | None:  # noqa: ANN001
        return await leader_marius_id(uow, project_id)

    async def _team(
        self, uow, project_id: UUID, *, leader_id: UUID  # noqa: ANN001
    ) -> list[ChatDirectoryEntry]:
        grants = await uow.seat_grants.list_by_project(project_id)
        role_rows = await uow.roles.list_by_project(project_id)
        roles = {r.id: r for r in role_rows}
        leader_ids = leader_role_ids(role_rows)
        entries: list[ChatDirectoryEntry] = []
        seen: set[UUID] = set()
        for g in grants:
            if g.role_id in leader_ids or g.marius_id == leader_id or g.marius_id in seen:
                continue
            seen.add(g.marius_id)
            worker = await uow.mariuses.get(g.marius_id)
            if worker is not None:
                # Resolve the worker's PROJECT role (SeatGrant.role_id → Role), never the
                # empty workspace-level Marius.role. Fall back to the key if the role row is
                # somehow missing so the entry is never blank.
                role = roles.get(g.role_id)
                entries.append(
                    ChatDirectoryEntry(
                        marius_id=worker.id,
                        name=worker.name,
                        role=(role.title if role else str(g.role_id)),
                        role_description=(role.description if role else ""),
                        liveness=str(worker.liveness),
                    )
                )
        return entries
