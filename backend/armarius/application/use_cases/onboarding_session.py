"""Onboarding use case (LLD §2.10) — the Workspace Agent interviews the Patron with a
guided, tick-select questionnaire and, on completion, materialises the agreed draft into a
real Project + roster.

The conversation is driven by an ``OnboardingBrain`` (``onboarding_brain.py``). The active
default is the ``DeterministicBrain``: a fixed plan of option questions that accumulates a
real draft — replacing the old keyword template that repeated the same reply every turn (#61).
A real Workspace-Agent runtime can drive the SAME contract by posting questions/completion to
the agent-facing endpoints; the deterministic brain is the always-available fallback.

Each ``start`` opens a FRESH session (any prior open session for the workspace is abandoned),
so re-entering "create a project with the agent" never resurrects stale chat history.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from armarius.application.use_cases.onboarding_brain import (
    DeterministicBrain,
    _leader_role,
    _project_name,
)
from armarius.application.use_cases.projects import ProjectService, RoleSpec
from armarius.application.use_cases.types import UowFactory
from armarius.application.use_cases.workspace_agent import WorkspaceAgentService
from armarius.domain.entities.onboarding import OnboardingSession, OnboardingStatus
from armarius.shared.clock import utcnow


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
        brain: DeterministicBrain | None = None,
    ) -> None:
        self._uow = uow_factory
        self._projects = projects
        self._ws_agent = workspace_agent
        self._brain = brain or DeterministicBrain()

    async def start(self, workspace_id: UUID) -> OnboardingSession:
        """Open a FRESH onboarding chat for a workspace and ask the first question.

        Any prior OPEN session for the workspace is abandoned first, so re-entering the
        agent flow starts clean instead of rejoining stale history (#61).
        """
        await self._ws_agent.ensure_workspace_agent(workspace_id)
        now = utcnow()
        async with self._uow() as uow:
            if await uow.workspaces.get(workspace_id) is None:
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
            session.collected = self._brain.start(session.collected)
            question = session.collected.get("pending_question")
            if question is not None:
                session.add_turn("agent", _question_text(question), now)
            await uow.onboardings.add(session)
            await uow.commit()
            return session

    async def answer(self, session_id: UUID, value: str) -> OnboardingSession:
        """Record the Patron's answer to the pending question and ask the next one."""
        now = utcnow()
        async with self._uow() as uow:
            session = await self._open(uow, session_id)
            session.add_turn("patron", value, now)
            session.collected = self._brain.answer(session.collected, value)
            question = session.collected.get("pending_question")
            if question is not None:
                session.add_turn("agent", _question_text(question), now)
            elif session.collected.get("phase") == "complete":
                draft = session.collected.get("draft") or {}
                names = ", ".join(r.get("title", "") for r in draft.get("roster", []))
                session.add_turn(
                    "agent",
                    f"Here's the plan: **{draft.get('name', '')}** with {names}. "
                    "Confirm to create it.",
                    now,
                )
            session.updated_at = now
            await uow.onboardings.update(session)
            await uow.commit()
            return session

    # ── real Workspace-Agent runtime callbacks (agent-driven mode) ──────────────────
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

    async def _open(self, uow, session_id: UUID) -> OnboardingSession:  # noqa: ANN001
        session = await uow.onboardings.get(session_id)
        if session is None:
            raise LookupError("onboarding session not found")
        return session


class OnboardingBusy(Exception):
    """Raised when a live WA posts a new question while the previous one is unanswered."""


def _as_datetime(value: object) -> datetime | None:
    if isinstance(value, datetime):
        return value
    if isinstance(value, str) and value.strip():
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    return None
