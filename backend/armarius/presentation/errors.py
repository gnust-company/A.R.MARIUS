"""Maps domain/use-case refusals to HTTP responses (keeps routers thin).

Every refusal now arrives as a **code plus its parameters** (FR-084a), so what a handler
has to decide is no longer *what to say* — only *what status to say it under*. That turns
forty near-identical handlers into one handler and the table below, where each row carries
the reason its status is what it is.

The body is the same shape for all of them: `detail` is the English rendering, for whoever
reads the raw response — an agent, a log, `curl`; `code` and `params` are what the screen
builds the patron's own sentence from.
"""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from armarius.application.use_cases.approvals import (
    CriteriaNotScoredError,
    NotReadyForSignatureError,
    ResponsiblePatronUnknown,
)
from armarius.application.use_cases.enrollment import GatewayUnreachable
from armarius.application.use_cases.onboarding_session import (
    OnboardingBusy,
    WorkspaceAgentUnavailable,
)
from armarius.application.use_cases.plans import PlanningError
from armarius.application.use_cases.projects import (
    DuplicateProjectKey,
    DuplicateRoleKey,
    SystemOnlyOperation,
)
from armarius.application.use_cases.recovery import (
    EscalationAnswerInvalid,
    NotOnTheLeadersRung,
)
from armarius.application.use_cases.tasks import (
    AlreadyAssignedError,
    ProjectNotReadyForTasks,
    TitleRequiredError,
)
from armarius.domain.entities.approval import RejectionNeedsReasonError
from armarius.domain.entities.checklist_item import (
    CriteriaLockedError,
    CriterionNotRatableError,
    EvidenceRequiredError,
)
from armarius.domain.entities.leader_chat import LeaderChatError
from armarius.domain.entities.marius import InviteError
from armarius.domain.entities.onboarding import OnboardingError
from armarius.domain.entities.task import (
    ArtifactRequiredError,
    CriteriaNotMetError,
    DependencyNotMetError,
    DescriptionLockedError,
    DescriptionRequiredError,
    SignaturesRequiredError,
    StalledTaskError,
    StatusReasonRequiredError,
    TaskTransitionError,
)
from armarius.domain.entities.task_dependency import TaskDependencyError
from armarius.domain.services.plan_gate import PlanGateError
from armarius.domain.services.project_key import InvalidProjectKey
from armarius.domain.services.project_rules import (
    InvalidPhaseTransition,
    InvalidProjectPlan,
    ProjectClosed,
)
from armarius.domain.services.wake_policy import WakeCauseRefused
from armarius.shared.errors import CodedError, Conflict, Forbidden, NotFound, Unauthorized

# ── who answers with what ─────────────────────────────────────────────────────
#
# Grouped for reading, not for resolution: the framework picks a handler by walking the
# raised exception's own class hierarchy, so a subclass registered here always beats the
# base it inherits from no matter where either row sits. Every row is a coded refusal; the
# comment on it says why that status and not another.

_ROUTING: tuple[tuple[type[Exception], int, str], ...] = (
    (NotFound, 404, "nothing at that id — and not-yours reads the same way (Constitution I)"),
    (Unauthorized, 401, "no usable credential on the call at all"),
    # 409 for the phase and state gates. The request is well formed; what refuses it is
    # the state of the thing it lands on, and the code says which rule so the board can
    # show the patron why rather than a bare "not allowed".
    (ProjectNotReadyForTasks, 409, "FR-003 — the gate is the project's phase, not a bad request"),
    (InvalidPhaseTransition, 409, "the phase the project is in refuses the move"),
    (ProjectClosed, 409, "FR-005 — a closed project is frozen: readable, never writable"),
    (WakeCauseRefused, 409, "FR-048a — the two closed cause lists, enforced at the door"),
    (PlanGateError, 409, "the plan is not at a point where this decision exists"),
    (PlanningError, 409, "same, one level up: the project's planning state refuses it"),
    (TaskTransitionError, 409, "the transition table refuses the move"),
    (ArtifactRequiredError, 409, "nothing published to review"),
    (DependencyNotMetError, 409, "a blocked_by task is unfinished (§1.3)"),
    (DescriptionRequiredError, 409, "FR-029 — a worker may not be handed a bare title"),
    (StatusReasonRequiredError, 409, "FR-030 — the move must say why"),
    (StalledTaskError, 409, "FR-058 — a task the system dropped is not closed quietly"),
    (DescriptionLockedError, 409, "FR-018 — the worker adds notes, not requirements"),
    (AlreadyAssignedError, 409, "one task, one worker"),
    (CriteriaLockedError, 409, "FR-019/FR-075 — the yardstick stops moving once work starts"),
    # The three refusals around scoring a criterion (FR-019, T178), for the same reason as
    # the gates above: the request is well formed and it is the task's own state — not yet
    # in review, nothing to cite, criteria still unrated — that says no.
    (CriterionNotRatableError, 409, "a criterion is scored while judging, not before"),
    (EvidenceRequiredError, 409, "a pass must name what proves it"),
    (CriteriaNotMetError, 409, "a criterion is still unrated or failed"),
    (CriteriaNotScoredError, 409, "signing before the yardstick has spoken"),
    (SignaturesRequiredError, 409, "FR-033 — a task closes on two signatures"),
    (NotOnTheLeadersRung, 409, "the ladder is not at the rung this action belongs to"),
    (NotReadyForSignatureError, 409, "signing happens while the task is in review"),
    (RejectionNeedsReasonError, 409, "a rejection the worker cannot act on is not one"),
    # 409, not 404: the task exists and the caller may see it — what is broken is the seat
    # record it points at, and saying so is the only way it gets fixed.
    (ResponsiblePatronUnknown, 409, "the seat record cannot name who signs"),
    (DuplicateRoleKey, 409, "that role key is taken in this roster"),
    (DuplicateProjectKey, 409, "project KEY already used in this workspace (JIRA-style)"),
    # No Leader seated / Leader offline / turn already running — the FE also disables the
    # box up-front when the Leader is offline (#82), so this is the second line, not the
    # first.
    (LeaderChatError, 409, "the Leader cannot take a turn right now"),
    (InviteError, 409, "the invite is not in a state this action applies to"),
    (OnboardingError, 409, "illegal session transition on a non-open chat"),
    (OnboardingBusy, 409, "one question at a time — the last one is unanswered"),
    # The Workspace Agent is not online (or a wake failed) — onboarding cannot proceed.
    # No fallback: tell the user to enroll or wake the agent (both start and mid-interview).
    (WorkspaceAgentUnavailable, 409, "the Workspace Agent is not there to interview with"),
    (EscalationAnswerInvalid, 409, "this escalation does not take that action"),
    (Conflict, 409, "a coded refusal that is about state and nothing more specific fits"),
    # 422 — the request was well formed as far as the wire is concerned, but what it asks
    # for cannot be made into a thing that exists.
    (TitleRequiredError, 422, "FR-070a — an edit may clear a deadline, never the name"),
    (TaskDependencyError, 422, "self-loop, duplicate, cross-project, or cycle"),
    (InvalidProjectPlan, 422, "hard roster composition rule (API_CONTRACT §3.1)"),
    (InvalidProjectKey, 422, "KEY malformed (2–10 uppercase, starts with a letter)"),
    # The operator-supplied gateway failed its reachability probe (issue #63): well formed,
    # but the target is not live.
    (GatewayUnreachable, 422, "the gateway did not answer its probe"),
    (SystemOnlyOperation, 403, "this door is the system's, not a caller's"),
    (Forbidden, 403, "the caller is known and may not do this"),
)


def _json(status_code: int, exc: Exception) -> JSONResponse:
    """One body shape for every refusal, coded or not.

    Anything that is not coded yet still answers with `detail` alone — the interface falls
    back to it, which is exactly what it did before the codes existed.
    """
    if isinstance(exc, CodedError):
        return JSONResponse(status_code=status_code, content=exc.to_payload())
    return JSONResponse(status_code=status_code, content={"detail": str(exc)})


def install_error_handlers(app: FastAPI) -> None:
    for exc_type, status_code, _why in _ROUTING:

        def _handler(
            _: Request, exc: Exception, *, _status: int = status_code
        ) -> JSONResponse:
            return _json(_status, exc)

        app.add_exception_handler(exc_type, _handler)

    # The three built-ins the codebase still raises directly, kept as the floor under the
    # table above: a repository that cannot find the row it was told to update, a value
    # that fails a check nobody has given a code yet, a permission check written inline.
    @app.exception_handler(LookupError)
    async def _not_found(_: Request, exc: LookupError) -> JSONResponse:
        if not isinstance(exc, CodedError) and not str(exc):
            return JSONResponse(status_code=404, content={"detail": "not found"})
        return _json(404, exc)

    @app.exception_handler(PermissionError)
    async def _forbidden(_: Request, exc: PermissionError) -> JSONResponse:
        return _json(403, exc)

    @app.exception_handler(ValueError)
    async def _bad_request(_: Request, exc: ValueError) -> JSONResponse:
        return _json(400, exc)
