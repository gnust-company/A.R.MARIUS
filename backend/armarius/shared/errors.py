"""A refusal is a code plus its parts, never a finished sentence (FR-084a).

A refusal has the same two readers a wake cause has, and they do not read the same
language. An agent calling the API has no interface language to pick from, so its copy
must be English (Constitution VII). The patron reads the very same refusal on screen, in
whichever language they chose. One sentence written here can only ever serve one of them.

So nothing here writes a sentence. Every refusal carries a **code** and the parameters
that fill it; the wire renders English from the table below for whoever reads the raw
response, and the interface renders its own phrase table for the screen. The two stay in
step because they key off the same code.

The parameters are the parts a sentence cannot be built without — an identifier, a status,
a list of what is still missing. What they must never be is another system sentence passed
as text: that is a sentence escaping this table, and it will reach a reader in the wrong
language. Where the wording genuinely differs (a list that may be empty), the answer is a
second code, not a parameter that is sometimes blank.
"""

from __future__ import annotations

import math

# A placeholder with nothing to fill it degrades to this instead of raising. A refusal
# that reads a little vaguely still tells the caller no; a refusal that blows up while
# being worded turns a 409 into a 500.
_UNKNOWN_PARAM = "(unknown)"

ENGLISH: dict[str, str] = {
    # ── nothing at that id ────────────────────────────────────────────────────
    "task_not_found": "Task not found.",
    "project_not_found": "Project not found.",
    "workspace_not_found": "Workspace not found.",
    "agent_not_found": "Agent not found.",
    "role_not_found": "Role not found.",
    "skill_not_found": "Skill not found.",
    "artifact_not_found": "Artifact not found.",
    "criterion_not_found": "Criterion not found.",
    "inbox_item_not_found": "Inbox item not found.",
    "seat_grant_not_found": "Seat grant not found.",
    "leader_chat_conversation_not_found": "Leader chat conversation not found.",
    "wakeup_not_found": "Wake-up request not found.",
    "task_or_agent_not_found": "Task or agent not found.",
    "onboarding_session_not_found": "Onboarding session not found.",
    "no_active_onboarding_session": "No onboarding session is open.",
    "run_not_found": "Run not found.",
    "machine_not_found": "Machine not found.",
    # The business layer calls this a *placement* because it is forbidden to know it is a
    # workplace on a machine (Constitution III); the sentence says "workplace" because that
    # is the word on the screen the person is looking at. Same thing, two audiences.
    "placement_not_found": "Workplace not found.",
    # The three ways a link code is dead. They are separate codes, not one code with a
    # reason parameter, because the screen says something different for each: retype it,
    # start again, or you already linked this machine.
    "daemon_link_code_not_found": "No such link code.",
    "daemon_link_code_expired": "That link code has expired.",
    "daemon_link_code_already_used": "That link code has already been used.",
    "plan_not_found": "Plan not found.",
    "skill_not_linked": "Skill '{slug}' is not linked to you.",
    "onboarding_session_has_no_workspace": "This onboarding session has no workspace.",
    "role_not_in_roster": "Role '{role}' is not in this project's roster.",
    "no_granted_seat": "No granted seat for that agent and role.",
    # ── who is calling ────────────────────────────────────────────────────────
    "missing_bearer_token": "Missing bearer token.",
    "invalid_agent_token": "Invalid agent token.",
    "invalid_machine_token": "Invalid or expired machine token.",
    "invalid_access_token": "Invalid or expired access token.",
    "invalid_refresh_token": "Invalid refresh token.",
    "invalid_credentials": "Invalid email or password.",
    "user_not_found": "User not found.",
    "user_inactive": "This user account is inactive.",
    "email_already_registered": "Email already registered.",
    # ── the project's own state ───────────────────────────────────────────────
    "project_closed": "This project is closed — its history is read-only.",
    "daemon_link_code_already_approved": "That link code has already been approved.",
    "daemon_link_code_unavailable": "Could not allocate a link code; please try again.",
    # ── knocking too often ────────────────────────────────────────────────────
    # Two codes rather than one, because the two readers do different things about it. The
    # person has typed codes that were not live and is told to stop and check; the machine
    # is asking faster than the pace it was handed and is told to slow down. Both carry the
    # wait in seconds, which is also what rides on the `Retry-After` header.
    "daemon_link_guessed_too_often": (
        "Too many link codes have been tried. Wait {seconds} seconds and try again."
    ),
    "daemon_link_polled_too_often": (
        "Asking too often. Wait {seconds} seconds before asking again."
    ),
    # A machine sweeps its own PATH and cannot find the same CLI twice, so a repeated
    # kind in one report is a broken caller rather than a machine with two of something.
    # Refused rather than collapsed, because collapsing it would decide on the caller's
    # behalf which of two disagreeing entries was meant.
    "workplace_reported_twice": "Agent CLI '{cli_kind}' was reported twice in one sync.",
    # Picked from a list that was right when the page loaded and has since stopped being
    # true — the CLI was uninstalled, or the machine turned out not to support links. The
    # reason travels as a code so the screen can say which of those it was.
    "placement_not_ready": "That workplace is not ready for work ({reason}).",
    # An agent is attached to exactly one workplace for life (FR-007). Reaching this means
    # something tried to attach a second one, which is the move that requirement forbids.
    "agent_already_placed": "That agent is already attached to a workplace.",
    # One name answers for one agent inside a workspace (FR-007h). Two of them leaves
    # nobody — patron or Leader — able to say which one they meant.
    "agent_name_taken": "An agent called '{name}' is already in this workspace.",
    "project_closed_no_wake": (
        "This project is closed — its agents are not woken any more."
    ),
    "project_phase_transition_invalid": "A project cannot go from '{current}' to '{target}'.",
    "leave_planning_via_plan_gate": (
        "A project leaves planning by having its plan approved, not by changing the phase "
        "directly."
    ),
    "project_key_invalid": (
        "A project key must be 2–10 uppercase characters and start with a letter "
        "(got {key})."
    ),
    "project_key_taken": "Project key '{key}' is already used in this workspace.",
    "unknown_plan_decision": (
        "Unknown plan decision '{decision}' — expected duyet, yeu_cau_chinh or hoi_lai."
    ),
    "role_keys_must_be_unique": "Two roles cannot share the key '{keys}' on one project.",
    "role_seats_full": "The '{role}' role already holds all {seats} of its seats.",
    "unknown_project_phase": "Unknown project phase '{phase}'.",
    "unknown_task_status": "Unknown task status '{status}'.",
    "unknown_inbox_status": "Unknown inbox status '{status}'.",
    "role_key_taken": "Role key '{key}' already exists in this project's roster.",
    "project_needs_one_leader_role": (
        "A project needs exactly one leader role, found {found}."
    ),
    "leader_role_needs_one_seat": "The leader role must have exactly one seat.",
    "project_needs_a_worker_role": "A project needs at least one worker role with a seat.",
    "role_needs_a_description": (
        "Every role needs a description of what it does — missing for: {roles}."
    ),
    "role_description_not_erasable": "A role's description cannot be blanked out.",
    "role_seat_held": "A role cannot be removed while an agent holds its seat.",
    "seat_grants_system_only": "Seat grants are issued by the system only.",
    "seat_revokes_system_only": "Seat revokes are issued by the system only.",
    "last_workspace": "You cannot delete your only workspace — create another one first.",
    # ── the plan and the context ──────────────────────────────────────────────
    "plan_only_while_planning": (
        "A plan can only be submitted while planning (the project is '{status}')."
    ),
    "no_plan_awaiting_decision": "There is no plan awaiting a decision (the plan is '{status}').",
    "project_has_no_plan": "This project has no plan yet.",
    "plan_self_approval": (
        "The Leader cannot decide on its own plan — this is the patron's call."
    ),
    "plan_change_needs_reason": (
        "Asking for changes or asking a question must say why — the Leader has nothing "
        "to act on otherwise."
    ),
    "no_context_awaiting_decision": "There is no context version awaiting a decision.",
    "context_send_back_needs_reason": "Sending a context back must say why.",
    "planning_needs_approved_context": (
        "The project cannot leave planning without an approved context."
    ),
    "no_patron_to_ask": (
        "This project has no patron to ask, so a change of requirement cannot be approved."
    ),
    "project_not_ready_for_tasks": (
        "The plan is not approved yet, so this project does not take real tasks "
        "(it is in '{status}')."
    ),
    # ── a task's own state ────────────────────────────────────────────────────
    "task_needs_title": "A task needs a title.",
    "task_needs_description": (
        "A task needs a full description before it goes to a worker."
    ),
    "task_description_locked": (
        "The worker adds progress notes; it does not rewrite the requirement it was given."
    ),
    "task_already_assigned": (
        "This task already has a worker. A task has exactly one: hand it over with a "
        "reason, or split it in two."
    ),
    "task_transition_invalid": "Cannot move a task from '{current}' to '{target}'.",
    "task_move_needs_reason": "Moving to '{target}' must say why.",
    "task_reopen_not_closed": "Only a closed task can be reopened; this one is '{status}'.",
    "task_reopen_needs_reason": "Reopening a closed task must say why.",
    # No "(because ...)" variant. The verdict became a code (T200), and a code reads as
    # noise to the agent while its English clause reads as the wrong language to the
    # patron — so the refusal names the flag, and the verdict stays on the task, where
    # both readers already get it in the language they read.
    "task_stalled_cannot_finish": (
        "A task flagged as stalled cannot be moved to done — clear the flag first."
    ),
    "task_needs_artifact": "A published artifact must be linked before review or done.",
    # FR-007k — what an agent may be set to comes from the place it works at, not from a
    # list anybody may send.
    "placement_option_unknown": "This workplace offers no setting called {option}.",
    "placement_option_value_unsupported": (
        "This workplace does not accept {value} for {option}."
    ),
    "task_needs_signatures": "A task closes only with both signatures.",
    "task_needs_signatures_named": (
        "A task closes only with both signatures — still missing: {missing}."
    ),
    "task_criteria_unmet": (
        "A task closes only when every acceptance criterion has passed."
    ),
    "task_criteria_unmet_named": (
        "A task closes only when every acceptance criterion has passed — still open: "
        "{unmet}."
    ),
    "task_dependencies_unmet": "Some tasks this one depends on are not done.",
    "task_dependencies_unmet_named": (
        "Some tasks this one depends on are not done: {blockers}."
    ),
    # ── dependency edges ──────────────────────────────────────────────────────
    "dependency_self_loop": "A task cannot depend on itself.",
    "dependency_cross_project": "A dependency must stay within one project.",
    "dependency_exists": "This dependency already exists.",
    # FR-032 wants the ring named, not just refused: a reader told only that "a cycle
    # would form" has to find it by hand, on a board where the edge they are adding is
    # the one thing that is *not* there yet.
    "dependency_cycle": "This dependency would close a cycle: {cycle}.",
    # ── acceptance criteria ───────────────────────────────────────────────────
    "criteria_locked": (
        "Acceptance criteria are set before the worker starts; this task is '{status}'. "
        "Changing them now is a change of requirement and needs the patron's approval."
    ),
    "criterion_not_ratable": (
        "A criterion is scored only while the task is in review; this task is '{status}'."
    ),
    "evidence_required": (
        "Passing '{criterion}' must point at a published artifact as the evidence."
    ),
    # ── signing off ───────────────────────────────────────────────────────────
    "not_ready_to_sign": (
        "This task is '{status}' — it is signed only while it is in review."
    ),
    "criteria_not_scored": (
        "Not every acceptance criterion has passed, so this cannot be signed yet — "
        "still open: {unmet}."
    ),
    "rejection_needs_reason": (
        "A rejection must say why — the worker needs to know what to fix."
    ),
    "signer_unknown_no_assignee": (
        "This task has no worker yet, so nobody knows who has to sign."
    ),
    "signer_unknown_no_granter": (
        "This agent's seat does not record who granted it, so the signer cannot be "
        "inferred (FR-034)."
    ),
    "signer_unknown_no_seat": "The agent on this task holds no seat on this project.",
    "not_the_signing_patron": (
        "Only the patron who granted the seat of the agent that did this work may sign it."
    ),
    # ── the recovery ladder ───────────────────────────────────────────────────
    "not_the_leaders_call": (
        "This task is not waiting on the Leader's decision, so no recovery action can be "
        "recorded."
    ),
    "not_yet_the_leaders_call": (
        "This task has not reached the Leader's rung yet, so it cannot go to the patron. "
        "The system is still retrying."
    ),
    "escalation_needs_a_task": "Only an escalation attached to a task takes this action.",
    "escalation_needs_task_service": "No task service is wired up to carry this out.",
    "reassign_needs_a_target": "Reassigning must say who to.",
    # ── talking to the Leader ─────────────────────────────────────────────────
    "no_leader_seated": "No Leader is seated on this project.",
    "leader_offline": "The Leader is offline — the chat is disabled until it comes back.",
    "leader_still_replying": "The Leader is still replying — wait for its answer.",
    "wake_pair_busy_run": "A run is already holding this agent and task.",
    "wake_pair_busy_wakeup": "A wake is already pending for this agent and task.",
    "wake_cause_refused": (
        "This agent cannot be woken: the cause is not one its role is woken for."
    ),
    # ── the agent roster ──────────────────────────────────────────────────────
    "agent_already_active": "This agent is already active.",
    "agent_revoked_cannot_activate": "A revoked agent cannot be activated.",
    "agent_cannot_revoke": "Cannot revoke an agent that is '{status}'.",
    "unknown_adapter": "Unknown adapter type '{adapter}'.",
    "gateway_unreachable": "The gateway could not be reached: {reason}",
    # ── the onboarding interview ──────────────────────────────────────────────
    "onboarding_cannot_message": "Cannot post to a '{status}' onboarding session.",
    "onboarding_cannot_finalize": "Cannot finalize a '{status}' onboarding session.",
    "onboarding_cannot_abandon": "Cannot abandon a '{status}' onboarding session.",
    "onboarding_question_pending": "A question is already awaiting an answer.",
    "workspace_agent_not_set_up": (
        "Set up the Workspace Agent first — invite an agent with 'Make Workspace Agent' "
        "and its gateway credentials, then make sure it is online and retry."
    ),
    "workspace_agent_no_interview": (
        "The Workspace Agent did not start the interview — check it is online and retry."
    ),
    "workspace_agent_silent": (
        "The Workspace Agent did not respond — check it is online and retry."
    ),
    "workspace_agent_unreachable": (
        "The Workspace Agent could not be reached — check it is online and retry."
    ),
    "workspace_agent_runtime_missing": (
        "The Workspace Agent runtime '{adapter}' is not available."
    ),
    # ── artifacts and skills ──────────────────────────────────────────────────
    "artifact_link_needs_uri": "A link artifact needs a URI.",
    "artifact_needs_content": "A {kind} artifact needs its content.",
    # The store could not hand back the bytes it was just given, so nothing was recorded
    # — the publish never happened and the caller should simply send it again (FR-020,
    # FR-020b). 502: the failure is the store's, not the request's.
    "artifact_store_unreadable": (
        "The artifact store did not keep the bytes it was given. Nothing was recorded — "
        "publish it again."
    ),
    "skill_md_not_found": (
        "No SKILL.md found at that URL. Point at a folder or repository containing one."
    ),
    "builtin_skill_undeletable": "Built-in skills cannot be deleted.",
    "not_a_github_url": "That does not look like a GitHub URL.",
    "github_error": "GitHub returned {status}: {reason}",
    "github_unreachable": "GitHub could not be reached: {reason}",
    # ── what a run may write about itself ─────────────────────────────────────
    # A tool's full output must never leave the machine it ran on (FR-043a). The cut happens
    # there; this refusal is what makes the rule true of the store rather than of one
    # program's good behaviour.
    # Asking for the rest of an event that has no rest. Reads as *not found* rather than as a
    # separate refusal: the thing being asked for does not exist, and that is the whole answer.
    "run_event_full_text_not_found": (
        "That event has nothing kept apart from it — its payload is already the whole thing."
    ),
    "tool_result_not_summarised": (
        "A tool result must arrive summarised, never whole. Send its size, its type and the "
        "opening bytes."
    ),
    # Said to a machine, so it is said in English (Constitution VII) and it names what to do:
    # the masking is the machine's job and it did not happen (FR-048).
    "credential_in_the_clear": (
        "This batch carries a credential in the clear. Mask secrets on the machine before "
        "sending them."
    ),
}


class _Defaulting(dict[str, str]):
    """Fills a missing placeholder instead of raising."""

    def __missing__(self, key: str) -> str:
        return _UNKNOWN_PARAM


def render_en(code: str, params: dict[str, str]) -> str:
    """The wire's copy of a refusal. An unknown code falls back to itself: a caller that
    reads an odd word still learns which rule said no, and can look the code up."""
    template = ENGLISH.get(code)
    if template is None:
        return code
    try:
        return template.format_map(_Defaulting(params))
    except Exception:  # pragma: no cover - defensive, format_map is total here
        return template


class CodedError(Exception):
    """A refusal that carries the cause code and the parts that fill it.

    ``str(exc)`` is the English rendering, so anything that logs or prints an exception
    keeps reading like before. What the response body carries is the code and the
    parameters — the sentence on the screen is built there, not here.
    """

    def __init__(self, code: str, /, **params: object) -> None:
        self.code = code
        self.params = {k: str(v) for k, v in params.items()}
        Exception.__init__(self, render_en(code, self.params))

    def to_payload(self) -> dict[str, object]:
        return {"detail": str(self), "code": self.code, "params": dict(self.params)}


class NotFound(LookupError, CodedError):
    """Nothing at that identifier.

    Still a `LookupError`, because a handful of callers catch that to mean "gone" and
    carry on; making the coded version a different branch of the tree would have silently
    turned those recoveries into crashes.
    """

    def __init__(self, code: str, /, **params: object) -> None:
        CodedError.__init__(self, code, **params)


class BadRequest(ValueError, CodedError):
    """The request itself does not hold together. `ValueError` for the same reason."""

    def __init__(self, code: str, /, **params: object) -> None:
        CodedError.__init__(self, code, **params)


class Forbidden(PermissionError, CodedError):
    """The caller is known and may not do this. `PermissionError` for the same reason."""

    def __init__(self, code: str, /, **params: object) -> None:
        CodedError.__init__(self, code, **params)


class Unauthorized(CodedError):
    """No usable credential on the call at all — 401, before any rule is even reached."""


class Conflict(CodedError):
    """The call is well formed; the state it lands in refuses it — 409."""


class TooManyRequests(CodedError):
    """The call is fine and the caller may make it — just not this often — 429.

    Carries `retry_after` as whole seconds rather than only in the message, because the
    number has two readers: a person sees the sentence, and a machine reads the header.
    Rounded **up**, so a caller that obeys it to the second is never refused a second time
    for having been half a second early.
    """

    def __init__(self, code: str, /, *, retry_after: float, **params: object) -> None:
        self.retry_after = max(1, math.ceil(retry_after))
        CodedError.__init__(self, code, seconds=self.retry_after, **params)


class ArtifactStoreUnreliable(CodedError):
    """The store failed the publish it was in the middle of — 502, and retryable.

    Deliberately not a `Conflict`: nothing about the task's state refused the call, the
    *store* did not keep what it was given (FR-020). A 5xx tells the caller — a daemon
    retrying a dropped upload (FR-020b) — that trying again is the right move, where a
    4xx would tell it to stop.
    """
