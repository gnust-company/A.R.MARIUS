"""Onboarding use case (LLD §2.10) — the Workspace Agent interviews the Patron and, on
completion, materialises the agreed draft into a real Project + roster.

There is **no scripted brain**. The Workspace Agent is a real runtime; it MUST be online for
the interview to start. On ``start`` and ``answer`` the service opens **one run** carrying the
onboarding guide (``build_onboarding_guide_prompt``) or the continuation prompt, and hands it
to the agent's adapter. The guided agent posts each question / its final draft back through
the agent-facing callbacks (``agent_post_question`` / ``agent_post_complete``).

**One turn is one run, at workspace level** (FR-040c) — no task, no project, because at this
point no project exists. That is what lets the interview authenticate with the same run token
every other agent call uses, instead of a third kind of credential minted for one screen
(FR-014a).

It also changes when the answer arrives. A run is put on a shelf and taken by whichever
machine is free; nothing here waits for it. So ``start`` and ``answer`` return a session that
does not yet carry the next question, and the screen is told to come back and read it when the
agent has spoken — see ``announce_onboarding_step``. What the patron does is unchanged: ask,
answer, ask again, and out comes a project and a roster (FR-040b).

Ready / failure is still the hard rule (#61, v3):

  - ``_wa_ready`` is ``True`` only for ``ONLINE`` / ``WORKING``. Anything else (Checking /
    Offline / Silent) ⇒ the session is **not** created and ``WorkspaceAgentUnavailable`` (→ 409)
    tells the user to enroll / wake the agent.
  - If the runtime refuses the turn outright — no such adapter, the adapter raising, or a
    hand-off that comes back failed — the session is **abandoned** and the same "not online"
    error is raised. No fallback, no queued turns.
  - If the turn is accepted and then ends without the agent saying anything, ``run_ended``
    abandons the session. That failure now arrives after the reply the patron already got, so
    it is told to the screen rather than raised at it.

Each ``start`` opens a FRESH session (any prior open session for the workspace is abandoned),
so re-entering "create a project with the agent" never resurrects stale chat history.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from datetime import datetime
from typing import Any
from uuid import UUID

from armarius.application.ports.adapter import AdapterRegistry, ExecContext
from armarius.application.ports.workspace_trace import (
    WorkspaceTracePublisher,
    announce_onboarding_step,
)
from armarius.application.use_cases.onboarding_brain import (
    _leader_role,
    _project_name,
    build_onboarding_answer_prompt,
    build_onboarding_guide_prompt,
)
from armarius.application.use_cases.projects import ProjectService, RoleSpec
from armarius.application.use_cases.types import UowFactory
from armarius.application.use_cases.workspace_agent import WorkspaceAgentService
from armarius.domain.entities.marius import Liveness, Marius
from armarius.domain.entities.onboarding import OnboardingSession, OnboardingStatus
from armarius.domain.entities.run import ACTIVE_RUN_STATUSES, Run, RunStatus, WakeSource
from armarius.domain.entities.wakeup import WakeupRequest, WakeupStatus
from armarius.domain.services.wake_reason import WakeReason, reason
from armarius.shared.clock import utcnow
from armarius.shared.errors import CodedError, NotFound

logger = logging.getLogger(__name__)

# How a run this service opened is closed when it ended inside the same call that opened it.
# Typed as the one call it makes rather than as the whole engine: this service has no other
# business with runs, and naming the whole engine here would invite it to grow some.
RunCloser = Callable[..., Awaitable[None]]

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


def _qa_pairs(transcript: list[dict[str, Any]]) -> list[tuple[str, str]]:
    """Pair each agent question with the patron answer that follows it — openclaw-style, so the
    continuation prompt carries the FULL answered history and the agent always knows what is
    collected (instead of relying on its own session memory, which degrades on a weak model).

    The agent transcript line is ``_question_text`` output (the question + its option bullets);
    we keep only the first line (the question itself) for a compact, readable history.
    """
    pairs: list[tuple[str, str]] = []
    pending_q: str | None = None
    for turn in transcript:
        role = turn.get("role")
        text = (turn.get("text") or "").strip()
        if role == "agent":
            pending_q = text.split("\n", 1)[0].strip() if text else None
        elif role == "patron" and pending_q and text:
            pairs.append((pending_q, text))
            pending_q = None
    return pairs


def _looks_like_leader(role: dict[str, Any]) -> bool:
    """An agent-supplied role that is clearly its (mistaken) attempt at the leader — the
    canonical Project Leader is always injected, so drop these to avoid a duplicate / mislabeled
    leader (#110)."""
    if role.get("is_leader"):
        return True
    if str(role.get("key", "")).lower() == "leader":
        return True
    return str(role.get("title", "")).lower() == "project leader"


def _renumber_repeats(rows: list[dict[str, object]]) -> None:
    """`backend`, `backend2`, `backend3` — in place, keeping the first row on its key.

    First wins because the leader row is first and its key is canonical: a worker the agent
    happened to key `leader` must be the one that moves.
    """
    taken: set[str] = set()
    for row in rows:
        base = str(row.get("key") or row.get("title") or "role")
        key, suffix = base, 2
        while key in taken:
            key = f"{base}{suffix}"
            suffix += 1
        taken.add(key)
        row["key"] = key


def plan_from_collected(collected: dict) -> dict:
    """Materialise the accumulated draft into ``{name, objective, roles, ...}`` for finalize.

    The Project Leader is canonical and ALWAYS present — the agent lists only WORKER roles (the
    onboarding prompt tells it so), mirroring the normal create-project path
    (``presentation/api/projects.py`` injects the leader; the caller supplies workers). Any role
    the (weak) agent still cast as the leader is dropped (``_looks_like_leader``) so
    ``validate_plan`` sees exactly one leader — the canonical one — not a mislabeled worker, and
    never a duplicate "Project Leader" (#110).
    """
    draft = collected.get("draft") or {}
    default_worker = {"key": "frontend", "title": "Frontend", "seats": 1,
                      "description": "Builds the user-facing UI."}
    raw = draft.get("roster") or [default_worker]
    kept = [{**r, "is_leader": False} for r in raw if not _looks_like_leader(r)]
    workers = kept or [default_worker]
    spec_rows = [_leader_role(), *workers]
    # Keys the agent drafted, made unique before they leave this function. `validate_plan`
    # refuses a repeated key outright, which is right for a roster a human typed — but here
    # the author is a model that reached for the same obvious word twice, and killing the
    # whole onboarding over that would make the patron redo a conversation to fix a
    # machine's word choice. Renumbered the same way the project-key door renumbers.
    _renumber_repeats(spec_rows)
    roles = [
        RoleSpec(
            key=r.get("key") or r.get("title", "role"),
            title=r.get("title", r.get("key", "Role")),
            seats=int(r.get("seats", 1)),
            is_leader=bool(r.get("is_leader", False)),
            # Spec 03 §3.1: every project role must carry a description the wake/leader-chat
            # prompts can show. Strict (#112): the agent's complete-draft schema requires a
            # description per worker (422 otherwise) and validate_plan rejects any empty one —
            # so we pass it straight through, no silent fallback. The canonical leader row
            # carries its own description.
            description=(r.get("description") or "").strip(),
            skill_ids=list(r.get("skills") or []),
        )
        for r in spec_rows
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
        *,
        workspace_trace: WorkspaceTracePublisher | None = None,
        close_run: RunCloser | None = None,
    ) -> None:
        self._uow = uow_factory
        self._projects = projects
        self._ws_agent = workspace_agent
        self._registry = registry
        # How the screen finds out the agent has spoken. Nothing here waits for the turn any
        # more, so without this the patron would be left looking at a chat that never moves.
        self._trace = workspace_trace
        # How a turn that ran here and now is closed. A turn handed to a machine is closed by
        # the machine reporting back; one an adapter carries out on the spot ends inside this
        # call, and a run nobody closes holds its agent's slot and its own live token for ever.
        self._close_run = close_run

    async def start(self, workspace_id: UUID) -> OnboardingSession:
        """Open a FRESH onboarding chat for a workspace and put the agent's first turn out.

        Any prior OPEN session for the workspace is abandoned first, so re-entering the
        agent flow starts clean instead of rejoining stale history (#61). Raises
        ``WorkspaceAgentUnavailable`` (→ 409) when the agent is not online or the runtime
        refuses the turn — no session is left stranded.

        Comes back **before the agent has asked anything**. The turn is a run, and a run is
        taken by a machine on its own rhythm (FR-040c); the question arrives on the
        workspace channel a moment later. What the patron sees is the chat opening with the
        agent about to speak, which is what it always looked like.
        """
        wa = await self._ws_agent.ensure_workspace_agent(workspace_id)
        if wa is None or not _wa_ready(wa):
            raise WorkspaceAgentUnavailable("workspace_agent_not_set_up")

        now = utcnow()
        async with self._uow() as uow:
            ws = await uow.workspaces.get(workspace_id)
            if ws is None:
                raise NotFound("workspace_not_found")
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
            session_id=str(session_id), workspace_name=workspace_name
        )
        await self._take_a_turn(wa, session_id, guide, reason("onboarding_opened"))

        async with self._uow() as uow:
            fresh = await uow.onboardings.get(session_id)
        if fresh is None:
            raise NotFound("onboarding_session_not_found")
        # The chat is already gone: the turn both started and ended inside the call above —
        # which is what an in-process runtime does — and it ended without a word. The patron
        # gets the same clear signal they always got rather than an empty, stuck chat.
        if fresh.status != OnboardingStatus.OPEN:
            raise WorkspaceAgentUnavailable("workspace_agent_no_interview")
        return fresh

    async def answer(self, session_id: UUID, value: str) -> OnboardingSession:
        """Record the Patron's answer and put the agent's next turn out.

        Raises ``WorkspaceAgentUnavailable`` (→ 409) if the agent is no longer online or the
        runtime refuses the turn — the session is abandoned and the caller cancels the chat.
        Like ``start``, it returns before the agent has answered: the next question arrives
        on the workspace channel.
        """
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
            history = _qa_pairs(session.transcript)
        if workspace_id is None:
            raise NotFound("onboarding_session_has_no_workspace")

        wa = await self._ws_agent.ensure_workspace_agent(workspace_id)
        if wa is None or not _wa_ready(wa):
            await self._abandon(session_id)
            raise WorkspaceAgentUnavailable("workspace_agent_not_set_up")
        answer_prompt = build_onboarding_answer_prompt(
            session_id=str(session_id), history=history
        )
        await self._take_a_turn(wa, session_id, answer_prompt, reason("onboarding_answered"))

        async with self._uow() as uow:
            fresh = await uow.onboardings.get(session_id)
        if fresh is None:
            raise NotFound("onboarding_session_not_found")
        if fresh.status != OnboardingStatus.OPEN:
            raise WorkspaceAgentUnavailable("workspace_agent_silent")
        return fresh

    # ── real Workspace-Agent runtime callbacks (the guided agent drives the interview) ──
    async def agent_post_question(
        self, session_id: UUID, question: dict, *, by_run: UUID
    ) -> OnboardingSession:
        """A live WA posts its next question. 1-at-a-time: reject if one is unanswered."""
        now = utcnow()
        async with self._uow() as uow:
            session = await self._driven_by(uow, session_id, by_run)
            if session.collected.get("pending_question") is not None:
                raise OnboardingBusy("onboarding_question_pending")
            session.collected = {
                **session.collected, "phase": "asking",
                "pending_question": question, "draft": None,
            }
            session.add_turn("agent", _question_text(question), now)
            session.updated_at = now
            await uow.onboardings.update(session)
            await uow.commit()
            asked = session
        await self._tell(asked.workspace_id, asked.id)
        return asked

    async def agent_post_complete(
        self, session_id: UUID, draft: dict, *, by_run: UUID
    ) -> OnboardingSession:
        """A live WA posts its final draft (project + roster) for the Patron to confirm."""
        now = utcnow()
        async with self._uow() as uow:
            session = await self._driven_by(uow, session_id, by_run)
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
            drafted = session
        await self._tell(drafted.workspace_id, drafted.id)
        return drafted

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
                raise NotFound("onboarding_session_not_found")
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

    # ── one turn of the interview, as a run ──────────────────────────────────────
    async def _take_a_turn(
        self, wa: Marius, session_id: UUID, prompt: str, cause: WakeReason
    ) -> None:
        """Open one workspace-level run for this chat and hand it to the agent's runtime.

        The run carries no task and no project, because at this point neither exists
        (FR-040c). Its message is written down with it rather than composed later: what the
        agent has to be told was settled the moment the patron acted, and there is no task
        to re-read for anything fresher (see ``WakeEngine.compose_packet``).

        Anything that refuses the turn outright — no such runtime, the adapter raising, a
        hand-off that comes back failed — abandons the session and raises
        ``WorkspaceAgentUnavailable`` so the caller surfaces a clear 409. A turn that is
        *accepted* is not waited for; see ``run_ended`` for the other ending.
        """
        try:
            adapter = self._registry.get(wa.adapter_type)
        except LookupError:
            await self._abandon(session_id)
            raise WorkspaceAgentUnavailable(
                "workspace_agent_runtime_missing", adapter=wa.adapter_type
            ) from None

        now = utcnow()
        run = Run(
            marius_id=wa.id,
            adapter_type=wa.adapter_type,
            # Somebody asked for this here and now, which is what this cause means. It is
            # deliberately not a cause of its own: the two closed lists say which causes may
            # wake a Leader and which may wake a worker (FR-048a), and the agent taking this
            # turn is wearing neither hat.
            wake_source=WakeSource.ON_DEMAND,
            trigger_causes=[cause],
            trigger_detail=cause.render_en(),
            status=RunStatus.QUEUED,
            created_at=now,
        )
        async with self._uow() as uow:
            session = await self._open(uow, session_id)
            session.driving_run_id = run.id
            session.updated_at = now
            await uow.onboardings.update(session)
            await uow.runs.add(run)
            await uow.wakeups.add(
                WakeupRequest(
                    marius_id=wa.id,
                    source=run.wake_source,
                    causes=[cause],
                    reason=cause.render_en(),
                    prompt=prompt,
                    status=WakeupStatus.DISPATCHED,
                    run_id=run.id,
                    created_at=now,
                )
            )
            await uow.commit()

        ctx = ExecContext(
            prompt=prompt,
            adapter_config=dict(wa.adapter_config or {}),
            session_params={
                "session_id": f"armarius:onboarding:{session_id}",
                "session_key": f"armarius:onboarding:{session_id}",
            },
            marius_id=wa.id,
            run_id=run.id,
            timeout_seconds=_WAKE_TIMEOUT_SECONDS,
        )
        try:
            result = await adapter.dispatch(ctx)
        except Exception:
            await self._settle(run.id, RunStatus.FAILED, "workspace_agent_unreachable")
            await self._abandon(session_id)
            raise WorkspaceAgentUnavailable("workspace_agent_unreachable") from None

        if result.status in ACTIVE_RUN_STATUSES:
            # Accepted and still going: it is on a shelf, or in flight somewhere this call
            # cannot watch. Whoever carries it out reports its end, and that report is what
            # reaches ``run_ended``.
            return
        # An adapter that carried the whole turn out inside `dispatch`. It is over, so it is
        # closed here — nobody else is going to — and put through the very same ending a turn
        # taken on a machine goes through. One rule for "the agent said nothing", not two.
        await self._settle(run.id, result.status, result.error)
        if result.status != RunStatus.COMPLETED:
            await self._abandon(session_id)
            raise WorkspaceAgentUnavailable("workspace_agent_silent")
        await self.run_ended(run.id)

    async def run_ended(self, run_id: UUID) -> None:
        """A turn of some interview is over — check the chat it was driving still has a life.

        The old road waited for the turn inside ``start``/``answer``, so an agent that said
        nothing could be reported as a 409 to the very call that was waiting. Nothing waits
        now, so the same failure has to be caught where it actually surfaces: at the end of
        the run. A chat whose turn ended with no question and no draft has nobody left to
        drive it, and leaving it open would leave the patron watching a screen that will
        never move again.

        Called for **every** run that ends, so it says nothing about runs that were not
        driving an interview.
        """
        async with self._uow() as uow:
            session = await uow.onboardings.get_by_run(run_id)
            if session is None or session.status != OnboardingStatus.OPEN:
                return
            spoke = bool(
                session.collected.get("pending_question") or session.collected.get("draft")
            )
            workspace_id = session.workspace_id
            session_id = session.id
        if spoke:
            return
        await self._abandon(session_id)
        await self._tell(workspace_id, session_id)

    async def _settle(
        self, run_id: UUID, status: RunStatus, error: str | None = None
    ) -> None:
        """Close a run this call is the end of. No-op when nothing was wired to close runs."""
        if self._close_run is None:
            return
        await self._close_run(run_id, status=status, error=error)

    async def _tell(self, workspace_id: UUID | None, session_id: UUID) -> None:
        """Tell the workspace its chat moved — best effort, like every other announcement.

        A channel that throws must never undo what it was announcing: the question is in the
        database either way, and the screen re-reads on its own rhythm as a fallback.
        """
        try:
            await announce_onboarding_step(self._trace, workspace_id, session_id)
        except Exception:
            logger.exception("could not announce onboarding session %s", session_id)

    async def _abandon(self, session_id: UUID) -> None:
        """Idempotently abandon a session (only if still OPEN) — used on the wake-fail path."""
        async with self._uow() as uow:
            session = await uow.onboardings.get(session_id)
            if session is not None and session.status == OnboardingStatus.OPEN:
                session.abandon()
                session.updated_at = utcnow()
                await uow.onboardings.update(session)
                await uow.commit()

    async def _driven_by(
        self,
        uow,  # noqa: ANN001 - concrete UoW
        session_id: UUID,
        run_id: UUID,
    ) -> OnboardingSession:
        """The chat this run is taking the turn of — or nothing it is allowed to write to.

        **A live token is not the same as a live turn.** A run's token stays good until that
        run is closed, and closing it is a machine reporting back, which happens some time
        after the agent has finished speaking. So there is a window in which the previous
        turn's token still opens the door while the chat has already moved on: the patron
        answers, which clears the pending question and hands the next turn to a new run, and
        the old run — retrying a request whose reply went missing, or simply slow — writes a
        question that belongs to a step already passed. The one-at-a-time guard cannot catch
        it, because clearing the pending question is exactly what answering does.

        `driving_run_id` is the answer, and it is the same answer read the other way round
        when a turn ends (`run_ended`). Refusing reads as *no such chat* rather than
        *forbidden*: a run reaching for a chat that is not its own learns nothing about
        whether that chat exists (Constitution I).

        A chat with no driving run — one opened before the interview became a run — is
        writable by nobody, which is correct: the road that drove it is gone.
        """
        session = await self._open(uow, session_id)
        if session.driving_run_id != run_id:
            raise NotFound("onboarding_session_not_found")
        return session

    async def _open(self, uow, session_id: UUID) -> OnboardingSession:  # noqa: ANN001
        session = await uow.onboardings.get(session_id)
        if session is None:
            raise NotFound("onboarding_session_not_found")
        return session


class OnboardingBusy(CodedError):
    """Raised when a live WA posts a new question while the previous one is unanswered."""


class WorkspaceAgentUnavailable(CodedError):
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
