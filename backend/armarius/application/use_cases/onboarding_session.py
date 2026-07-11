"""Onboarding use case (LLD §2.10) — the Workspace Agent interviews the Patron and, on
completion, materialises the agreed draft into a real Project + roster.

There is **no scripted brain**. The Workspace Agent is a real runtime behind its adapter; it
MUST be online and wake-able to run the interview. On ``start`` and ``answer`` the service wakes
the agent with the onboarding guide (``build_onboarding_guide_prompt``); the guided agent posts
each question / its final draft back through the agent-facing callbacks
(``agent_post_question`` / ``agent_post_complete``). The wake is one **bounded turn** — the agent
asks one question, posts it, and ends its run; the service re-reads the now-populated session and
returns it in the same HTTP response (the Patron gets the next question synchronously).

Ready / wake-fail is the hard rule (#61, v3):

  - ``_wa_ready`` is ``True`` only for ``ONLINE`` / ``WORKING``. Anything else (Checking /
    Offline / Silent) ⇒ the session is **not** created and ``WorkspaceAgentUnavailable`` (→ 409)
    tells the user to enroll / wake the agent.
  - If a wake fails at start *or* mid-interview (the agent went offline, the adapter raised, or
    the run returned ``FAILED`` / ``TIMED_OUT`` / nothing useful), the session is **abandoned**
    and the same "not online" error is raised. No fallback, no queued turns.

Each ``start`` opens a FRESH session (any prior open session for the workspace is abandoned),
so re-entering "create a project with the agent" never resurrectes stale chat history.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from armarius.application.ports.adapter import AdapterRegistry, ExecContext
from armarius.application.use_cases.onboarding_brain import (
    _leader_role,
    _project_name,
    build_onboarding_guide_prompt,
)
from armarius.application.use_cases.projects import ProjectService, RoleSpec
from armarius.application.use_cases.types import UowFactory
from armarius.application.use_cases.workspace_agent import WorkspaceAgentService
from armarius.domain.entities.marius import Liveness, Marius
from armarius.domain.entities.onboarding import OnboardingSession, OnboardingStatus
from armarius.domain.entities.run import RunStatus
from armarius.shared.clock import utcnow

# Online/Working is the only "ready" for onboarding (LLD §10). Checking / Offline / Silent
# means the agent cannot take a turn right now — fail fast rather than queue.
_READY = (Liveness.ONLINE, Liveness.WORKING)
# One question is one bounded turn; the agent should ask and end its run in seconds. A wake that
# cannot produce a question in this window is treated as a failure (the agent is stuck/offline).
_WAKE_TIMEOUT_SECONDS = 120


def _wa_ready(wa: Marius) -> bool:
    return wa.liveness in _READY


def _question_text(question: dict) -> str:
    """A human-readable transcript line for a question (the interactive panel uses the
    structured ``pending_question``; this keeps the scrollback readable)."""
    lines = [question.get("question", "")]
    for opt in question.get("options", []):
        lines.append(f"  • {opt.get('label', '')}")
    return "\n".join(lines)


def plan_from_collected(collected: dict) -> dict:
    """Materialise the accumulated draft into ``{name, objective, roles, ...}`` for finalize.

    Falls back to a minimal valid plan if the draft is missing, so finalize can always create
    a valid project + roster (a Project needs one leader + ≥1 worker).
    """
    draft = collected.get("draft") or {}
    raw_roles = draft.get("roster") or [_leader_role(), *[
        {"key": "frontend", "title": "Frontend", "seats": 1, "is_leader": False,
         "description": "Builds the user-facing UI."},
    ]]
    roles = [
        RoleSpec(
            key=r.get("key") or r.get("title", "role"),
            title=r.get("title", r.get("key", "Role")),
            seats=int(r.get("seats", 1)),
            is_leader=bool(r.get("is_leader", False)),
            description=r.get("description", ""),
            skill_ids=list(r.get("skills") or []),
        )
        for r in raw_roles
    ]
    objective = (draft.get("objective") or "").strip() or "New project"
    name = (draft.get("name") or "").strip() or _project_name(objective)
    return {
        "name": name,
        "objective": objective,
        "roles": roles,
        "success_metrics": draft.get("success_metrics"),
        "target_date": draft.get("target_date"),
        "context": draft.get("context"),
    }


# ── the use case ──────────────────────────────────────────────────────────────────


class OnboardingService:
    def __init__(
        self,
        uow_factory: UowFactory,
        projects: ProjectService,
        workspace_agent: WorkspaceAgentService,
        registry: AdapterRegistry,
        base_url: str,
    ) -> None:
        self._uow = uow_factory
        self._projects = projects
        self._ws_agent = workspace_agent
        self._registry = registry
        self._base_url = base_url.rstrip("/")

    async def start(self, workspace_id: UUID) -> OnboardingSession:
        """Open a FRESH onboarding chat for a workspace and wake the agent to ask its first
        question.

        Any prior OPEN session for the workspace is abandoned first, so re-entering the
        agent flow starts clean instead of rejoining stale history (#61). Raises
        ``WorkspaceAgentUnavailable`` (→ 409) when the agent is not online or the wake fails —
        no session is left stranded.
        """
        wa = await self._ws_agent.ensure_workspace_agent(workspace_id)
        if wa is None or not _wa_ready(wa):
            raise WorkspaceAgentUnavailable(
                "set up the Workspace Agent first — invite an agent with 'Make Workspace "
                "Agent' and its gateway creds, then ensure it is online and retry"
            )

        now = utcnow()
        async with self._uow() as uow:
            ws = await uow.workspaces.get(workspace_id)
            if ws is None:
                raise LookupError("workspace not found")
            # Retire any still-open session so the new one is the only live chat.
            for prior in await uow.onboardings.list_by_workspace(workspace_id):
                if prior.status == OnboardingStatus.OPEN:
                    prior.abandon()
                    prior.updated_at = now
                    await uow.onboardings.update(prior)

            session = OnboardingSession(
                workspace_id=workspace_id, created_at=now, updated_at=now
            )
            session.collected = {
                "phase": "asking", "answers": {},
                "pending_question": None, "draft": None,
            }
            await uow.onboardings.add(session)
            await uow.commit()
            session_id = session.id
            workspace_name = ws.name

        guide = build_onboarding_guide_prompt(
            base_url=self._base_url, session_id=str(session_id), workspace_name=workspace_name
        )
        await self._wake(wa, session_id, guide)

        async with self._uow() as uow:
            fresh = await uow.onboardings.get(session_id)
        if fresh is None:
            raise LookupError("onboarding session not found")
        # The wake completed but the agent never asked anything / posted a draft → treat as a
        # failure so the user always gets a clear signal (never an empty, stuck chat).
        if not (fresh.collected.get("pending_question") or fresh.collected.get("draft")):
            await self._abandon(session_id)
            raise WorkspaceAgentUnavailable(
                "the Workspace Agent did not start the interview — check it is online and retry"
            )
        return fresh

    async def answer(self, session_id: UUID, value: str) -> OnboardingSession:
        """Record the Patron's answer and wake the agent to ask the next question (or post the
        draft). Raises ``WorkspaceAgentUnavailable`` (→ 409) if the agent is no longer online or
        the wake fails — the session is abandoned and the caller cancels the chat."""
        now = utcnow()
        async with self._uow() as uow:
            session = await self._open(uow, session_id)
            session.add_turn("patron", value, now)
            # The pending question is answered — clear it so the agent's next callback is not
            # rejected by the one-at-a-time guard (``agent_post_question`` raises OnboardingBusy
            # while a question is still pending).
            session.collected = {**session.collected, "pending_question": None}
            session.updated_at = now
            await uow.onboardings.update(session)
            await uow.commit()
            workspace_id = session.workspace_id
        if workspace_id is None:
            raise LookupError("onboarding session has no workspace")

        wa = await self._ws_agent.ensure_workspace_agent(workspace_id)
        if wa is None or not _wa_ready(wa):
            await self._abandon(session_id)
            raise WorkspaceAgentUnavailable(
                "set up the Workspace Agent first — invite an agent with 'Make Workspace "
                "Agent' and its gateway creds, then ensure it is online and retry"
            )
        await self._wake(wa, session_id, self._answer_prompt(value))

        async with self._uow() as uow:
            fresh = await uow.onboardings.get(session_id)
        if fresh is None:
            raise LookupError("onboarding session not found")
        if not (fresh.collected.get("pending_question") or fresh.collected.get("draft")):
            await self._abandon(session_id)
            raise WorkspaceAgentUnavailable(
                "the Workspace Agent did not respond — check it is online and retry"
            )
        return fresh

    # ── real Workspace-Agent runtime callbacks (the guided agent drives the interview) ──
    async def agent_post_question(self, session_id: UUID, question: dict) -> OnboardingSession:
        """A live WA posts its next question. 1-at-a-time: reject if one is unanswered."""
        now = utcnow()
        async with self._uow() as uow:
            session = await self._open(uow, session_id)
            if session.collected.get("pending_question") is not None:
                raise OnboardingBusy("a question is already awaiting an answer")
            session.collected = {
                **session.collected, "phase": "asking",
                "pending_question": question, "draft": None,
            }
            session.add_turn("agent", _question_text(question), now)
            session.updated_at = now
            await uow.onboardings.update(session)
            await uow.commit()
            return session

    async def agent_post_complete(self, session_id: UUID, draft: dict) -> OnboardingSession:
        """A live WA posts its final draft (project + roster) for the Patron to confirm."""
        now = utcnow()
        async with self._uow() as uow:
            session = await self._open(uow, session_id)
            session.collected = {
                **session.collected, "phase": "complete",
                "pending_question": None, "draft": draft,
            }
            names = ", ".join(r.get("title", "") for r in draft.get("roster", []))
            session.add_turn(
                "agent",
                f"Here's the plan: **{draft.get('name', '')}** with {names}. Confirm to create it.",
                now,
            )
            session.updated_at = now
            await uow.onboardings.update(session)
            await uow.commit()
            return session

    async def finalize(
        self, session_id: UUID, *, created_by_user_id: str | None = None
    ) -> OnboardingSession:
        """Materialise the agreed draft into a real Project + roster (``setup`` status)."""
        async with self._uow() as uow:
            session = await self._open(uow, session_id)
            plan = plan_from_collected(session.collected)
            workspace_id = session.workspace_id
            role_names = ", ".join(r.title for r in plan["roles"])
            session.add_turn(
                "agent", f"Creating **{plan['name']}** with: {role_names}.", utcnow()
            )

        project = await self._projects.create_project(
            workspace_id=workspace_id,  # type: ignore[arg-type]
            name=plan["name"],
            roles=plan["roles"],
            objective=plan["objective"],
            success_metrics=plan["success_metrics"],
            target_date=_as_datetime(plan["target_date"]),
            context=plan["context"],
            created_by_user_id=created_by_user_id,
        )

        async with self._uow() as uow:
            fresh = await uow.onboardings.get(session_id)
            if fresh is None:
                raise LookupError("onboarding session not found")
            fresh.finalize(project.id)  # OPEN → FINALIZED
            fresh.updated_at = utcnow()
            await uow.onboardings.update(fresh)
            await uow.commit()
            return fresh

    async def abandon(self, session_id: UUID) -> OnboardingSession:
        now = utcnow()
        async with self._uow() as uow:
            session = await self._open(uow, session_id)
            session.abandon()  # OPEN → ABANDONED
            session.updated_at = now
            await uow.onboardings.update(session)
            await uow.commit()
            return session

    async def get(self, session_id: UUID) -> OnboardingSession | None:
        async with self._uow() as uow:
            return await uow.onboardings.get(session_id)

    async def active_for(self, workspace_id: UUID) -> OnboardingSession | None:
        """The workspace's most recent OPEN session, if any (one live chat at a time)."""
        async with self._uow() as uow:
            sessions = await uow.onboardings.list_by_workspace(workspace_id)
        return next((s for s in sessions if s.status.value == "open"), None)

    # ── wake + fail handling ──────────────────────────────────────────────────────
    async def _wake(self, wa: Marius, session_id: UUID, prompt: str) -> None:
        """Run one bounded wake against the Workspace Agent.

        Any failure (unknown adapter, the adapter raising, or the run not completing) abandons
        the session and raises ``WorkspaceAgentUnavailable`` so the caller surfaces a clear 409.
        """
        try:
            adapter = self._registry.get(wa.adapter_type)
        except LookupError:
            await self._abandon(session_id)
            raise WorkspaceAgentUnavailable(
                f"the Workspace Agent runtime '{wa.adapter_type}' is not available"
            ) from None
        ctx = ExecContext(
            prompt=prompt,
            adapter_config=dict(wa.adapter_config or {}),
            session_params={
                "session_id": f"armarius:onboarding:{session_id}",
                "session_key": f"armarius:onboarding:{session_id}",
            },
            marius_id=wa.id,
            timeout_seconds=_WAKE_TIMEOUT_SECONDS,
        )
        try:
            result = await adapter.execute(ctx)
        except Exception:
            await self._abandon(session_id)
            raise WorkspaceAgentUnavailable(
                "the Workspace Agent could not be reached — check it is online and retry"
            ) from None
        if result.status != RunStatus.COMPLETED:
            await self._abandon(session_id)
            raise WorkspaceAgentUnavailable(
                "the Workspace Agent did not respond — check it is online and retry"
            )

    async def _abandon(self, session_id: UUID) -> None:
        """Idempotently abandon a session (only if still OPEN) — used on the wake-fail path."""
        async with self._uow() as uow:
            session = await uow.onboardings.get(session_id)
            if session is not None and session.status == OnboardingStatus.OPEN:
                session.abandon()
                session.updated_at = utcnow()
                await uow.onboardings.update(session)
                await uow.commit()

    @staticmethod
    def _answer_prompt(value: str) -> str:
        return (
            "ARMARIUS · PROJECT ONBOARDING (continued)\n\n"
            f"The owner answered: {value}\n\n"
            "Decide the single next question from the running context and POST it (one at a "
            "time), or POST the final draft if you now have enough to stand the project up.\n"
        )

    async def _open(self, uow, session_id: UUID) -> OnboardingSession:  # noqa: ANN001
        session = await uow.onboardings.get(session_id)
        if session is None:
            raise LookupError("onboarding session not found")
        return session


class OnboardingBusy(Exception):
    """Raised when a live WA posts a new question while the previous one is unanswered."""


class WorkspaceAgentUnavailable(Exception):
    """The Workspace Agent is not online, or a wake failed — onboarding cannot proceed.

    Mapped to HTTP 409 so the client can tell the user to enroll/wake the agent (no fallback).
    """


def _as_datetime(value: object) -> datetime | None:
    if isinstance(value, datetime):
        return value
    if isinstance(value, str) and value.strip():
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    return None
