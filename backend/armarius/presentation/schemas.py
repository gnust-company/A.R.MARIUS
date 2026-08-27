"""Pydantic request/response schemas for the HTTP API."""

from __future__ import annotations

import base64
import hashlib
from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from armarius.application.use_cases.plans import MajorChangeArea
from armarius.domain.services.project_key import PROJECT_KEY_RE
from armarius.domain.services.push_reason_rules import stall_text_en


class _Out(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# --------------------------------------------------------------------- workspace
class CreateWorkspaceIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)


class UpdateWorkspaceIn(BaseModel):
    """Rename a workspace (slug is re-derived from the name)."""

    name: str = Field(min_length=1, max_length=200)


class WorkspaceOut(_Out):
    id: UUID
    name: str
    slug: str
    # The designated host Marius (#32) — the FE derives each agent's "WA" badge from it.
    workspace_agent_id: UUID | None = None
    created_at: datetime | None = None


class CreateProjectIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str | None = None


class ProjectOut(_Out):
    id: UUID
    workspace_id: UUID | None = None
    name: str
    slug: str
    key: str | None = None
    description: str | None = None
    # Lifecycle (setup → active → archived) + brief so the project list can render a real
    # status chip and objective line without opening the detail view.
    status: str = "setup"
    objective: str | None = None
    # Seat fill for the project card (filled / total) so the list shows the real roster
    # count without opening each project's detail. Stamped by the list endpoint; the
    # entity itself has no seats, so these default to 0.
    seats_total: int = 0
    seats_filled: int = 0
    created_at: datetime | None = None


# ------------------------------------------------- projects + roster (contract §3)
class LeaderIn(BaseModel):
    # Mô tả vai trò Leader — BẮT BUỘC: vào prompt wake/leader-chat để đồng đội biết vai trò làm gì
    # (#93, strict #112). Thiếu/rỗng ⇒ 422 rõ ràng ngay ở tầng API.
    description: str = Field(min_length=1, max_length=2000)
    marius_id: UUID | None = None


class RoleIn(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    seats: int = Field(default=1, ge=1)
    # BẮT BUỘC: mỗi role phải nêu nó làm gì (spec 03 §3.1). Thiếu/rỗng ⇒ 422 (#112).
    description: str = Field(min_length=1, max_length=2000)
    skill_ids: list[str] = Field(default_factory=list)
    marius_ids: list[UUID | None] = Field(default_factory=list)  # pre-seat (len ≤ seats)


class CreateProjectPlanIn(BaseModel):
    """A complete seat plan (API_CONTRACT §3.1): one leader + ≥1 worker role."""

    name: str = Field(min_length=1, max_length=200)
    description: str | None = None
    # JIRA-style project KEY — the prefix of task identifiers "{key}-{seq}". Optional:
    # when omitted (or blank) the service suggests one from `name` and auto-uniquifies.
    key: str | None = Field(
        default=None, min_length=2, max_length=10, pattern=PROJECT_KEY_RE.pattern
    )
    mode: str = "manual"
    objective: str | None = None
    success_metrics: dict | None = None
    target_date: datetime | None = None
    github_url: str | None = None
    context: str | None = None
    # Leader is REQUIRED (no empty default): strict #112 means the Patron must describe the
    # leader role too, so the plan can never carry a description-less leader.
    leader: LeaderIn
    roles: list[RoleIn] = Field(default_factory=list)
    settings: dict | None = None
    onboarding_session_id: UUID | None = None


class UpdateProjectIn(BaseModel):
    description: str | None = None
    objective: str | None = None
    success_metrics: dict | None = None
    target_date: datetime | None = None
    github_url: str | None = None
    context: str | None = None
    settings: dict | None = None


class SeatOut(BaseModel):
    marius_id: UUID
    name: str
    role_key: str
    liveness: str
    is_primary: bool


class RosterRoleOut(BaseModel):
    key: str
    title: str
    seats: int
    is_leader: bool
    description: str
    skill_ids: list[str]
    filled: int
    seated: list[SeatOut]


class ProjectDetailOut(_Out):
    id: UUID
    workspace_id: UUID | None = None
    name: str
    slug: str
    key: str | None = None
    description: str | None = None
    status: str
    objective: str | None = None
    success_metrics: dict | None = None
    target_date: datetime | None = None
    github_url: str | None = None
    context: str | None = None
    settings: dict | None = None
    created_by_user_id: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    roster: list[RosterRoleOut] = Field(default_factory=list)


class AddRoleIn(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    seats: int = Field(default=1, ge=1)
    # BẮT BUỘC: thêm role mới cũng phải nêu nó làm gì. Thiếu/rỗng ⇒ 422 (#112).
    description: str = Field(min_length=1, max_length=2000)
    skill_ids: list[str] = Field(default_factory=list)
    is_leader: bool = False


class UpdateRoleIn(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    seats: int | None = Field(default=None, ge=1)
    # None ⇒ giữ nguyên; nhưng nếu SỬA thì không được về rỗng — mọi role phải có mô tả
    # (spec 03 §3.1). Chặn chuỗi rỗng ngay ở schema (422); toàn-khoảng-trắng chặn ở use-case.
    description: str | None = Field(default=None, min_length=1, max_length=2000)
    skill_ids: list[str] | None = None


class RoleOut(_Out):
    id: UUID
    project_id: UUID | None = None
    key: str
    title: str
    seats: int
    is_leader: bool
    description: str = ""
    skill_ids: list[str] = Field(default_factory=list)
    created_at: datetime | None = None


# ------------------------------------------------------- labels (contract §5.4)
class CreateLabelIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    color: str = Field(default="", max_length=20)


class LabelOut(_Out):
    id: UUID
    workspace_id: UUID | None = None
    name: str
    color: str = ""
    created_at: datetime | None = None


class GrantSeatIn(BaseModel):
    marius_id: UUID
    role_key: str = Field(min_length=1, max_length=200)


class SignApprovalIn(BaseModel):
    """One signature on a task's output (spec 001 FR-033, FR-040)."""

    approve: bool
    # Required when refusing: a rejection with no feedback leaves the worker nothing to
    # fix, and the next action written onto the task would be empty.
    reason: str | None = Field(default=None, max_length=2000)


class SprintSummaryIn(BaseModel):
    """The Leader's wrap-up when a batch of work closes (FR-043)."""

    summary: str = Field(min_length=1, max_length=20000)


class AutoApprovalIn(BaseModel):
    enabled: bool


class AutoApprovalOut(_Out):
    project_id: UUID | None = None
    user_id: str = ""
    enabled: bool = False
    updated_at: datetime | None = None


class ApprovalOut(_Out):
    """One recorded signature (spec 001 §8)."""

    id: UUID
    task_id: UUID | None = None
    round: int = 1
    signer_kind: str
    signer_marius_id: UUID | None = None
    signer_user_id: str | None = None
    result: str
    reason: str | None = None
    is_auto: bool = False
    signed_at: datetime | None = None


class SeatGrantOut(_Out):
    """A live seat. There is no `status`: a vacated seat is a deleted row (T199)."""

    id: UUID
    project_id: UUID | None = None
    role_key: str
    marius_id: UUID | None = None
    # Who put this agent in the seat (FR-034) — what decides who signs for its output.
    granted_by_user_id: str | None = None
    granted_at: datetime | None = None
    created_at: datetime | None = None


# ------------------------------------------------------------------------ skill
class SkillOut(_Out):
    id: UUID
    workspace_id: UUID | None = None
    slug: str
    name: str
    description: str = ""
    source: str
    source_url: str = ""
    files: dict[str, str] = Field(default_factory=dict)
    created_at: datetime | None = None


class ManualSkillIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str = ""


class ImportSkillIn(BaseModel):
    source_url: str = Field(min_length=1, max_length=2000)


class UpdateSkillIn(BaseModel):
    files: dict[str, str] = Field(default_factory=dict)


# ----------------------------------------------------------------------- marius
class RegisterMariusIn(BaseModel):
    """Everything it takes to make an agent (FR-007g).

    There is no gateway address and no key here any more. Those existed because Armarius
    used to reach an agent by calling somebody else's server; the daemon runs on the user's
    own machine and asks for work instead, so there is nothing left to address (FR-040a).
    """

    name: str = Field(min_length=1, max_length=200)
    # What the agent is told to be, sent down on every run (FR-007i).
    instructions: str = Field(default="", max_length=20000)
    # What the team calls it. Never sent to the agent (FR-007j).
    description: str = Field(default="", max_length=2000)
    skills: list[str] = Field(default_factory=list)
    skill_ids: list[str] = Field(default_factory=list)
    # There is deliberately no runtime field here. Which tool carries an agent's turn follows
    # from the workplace it is put on — a thing the person can see and reason about — not from
    # a separate menu they have no way to answer well. A caller sending one is ignored rather
    # than obeyed: a value from the wire could name a runtime nothing can run.
    # Where this agent will work. Required, with no default (FR-007f): an agent is attached
    # to one workplace for life, so the choice cannot be postponed and there is no such
    # thing as leaving it blank. Missing it is refused here, before any agent exists.
    workplace_id: UUID
    # Seat this Marius as the workspace's host on creation (#32); a sitting host is
    # demoted to a plain agent (kept, not revoked).
    is_workspace_agent: bool = False


class UpdateMariusIn(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    role: str | None = None
    skills: list[str] | None = None
    skill_ids: list[str] | None = None
    adapter_type: str | None = None
    adapter_config: dict | None = None


class InstallSkillsIn(BaseModel):
    """Link additional skills to an already-invited agent and push an install prompt (issue #74).

    The skill_ids are merged into the agent's existing links (duplicates de-duped, order
    preserved). A one-time skill-install prompt is then pushed to the agent over its
    gateway so it fetches and installs the newly linked skills.
    """

    skill_ids: list[str] = Field(default_factory=list)


class InstallSkillsOut(_Out):
    """Result of linking skills to an agent (issue #74, FR-011c).

    Nothing is pushed any more. Skills travel down with the work, inside the claim packet
    (FR-011b), so linking one here is the whole of the act — the agent picks it up on its
    next run and confirms it out of band.
    """

    marius_id: UUID
    skill_ids: list[str] = Field(default_factory=list)
    installed: list[str] = Field(default_factory=list)  # slugs linked this call (now "pending")


class MariusOut(_Out):
    id: UUID
    workspace_id: UUID | None = None
    name: str
    role: str
    instructions: str = ""
    description: str = ""
    skills: list[str]
    skill_ids: list[str] = Field(default_factory=list)
    adapter_type: str
    liveness: str
    # Why this agent has nowhere to work, when it has nowhere to work (FR-006c). A code,
    # never a sentence — two audiences read this in two languages and only the screen knows
    # which one it is talking to (Constitution VI + VII).
    #
    # `null` is not the same as "online". Liveness is decided on a clock and this is decided
    # on the state of a place, so an agent can be online with a reason attached — the place
    # shut a second ago and the clock has not caught up. The screen shows the reason beside
    # whatever the status says rather than instead of it; anything that tried to derive one
    # of the two from the other would be inventing an agreement neither field promises.
    offline_reason: str | None = None
    # Invite lifecycle (operator-invite: invited → approved). `adapter_config` and
    # `agent_token` are deliberately omitted — they are secrets, never serialized out.
    invite_status: str | None = None
    last_seen_at: datetime | None = None
    created_at: datetime | None = None


class WorkplaceChoiceOut(_Out):
    """One workplace the person may put an agent on (FR-007f).

    Only ready ones are ever listed, so there is no `ready` flag to render: a workplace that
    cannot take work has no business being on a list whose only purpose is choosing one.
    """

    id: UUID
    cli_kind: str
    # The machine's own readable name — the only thing separating the same CLI on two of
    # the person's machines (FR-003).
    machine_name: str


class MariusCreatedOut(MariusOut):
    """The agent that was just created. Identical to MariusOut — there is no send to report
    on any more, because nothing is sent (FR-007g)."""


class MetaOut(BaseModel):
    version: str
    public_base_url: str
    adapters: list[str]


# ------------------------------------------------------------------------- task
class EditTaskIn(BaseModel):
    """The patron rewriting a task after it exists (FR-070a).

    Every field is optional, and *omitted* is not the same as *sent empty*: sending
    ``due_date: null`` wipes a deadline typed in by mistake, while leaving `due_date` out
    keeps whatever is there. The route reads `model_fields_set` to tell the two apart, so
    do not give these fields defaults that hide the difference.
    """

    title: str | None = Field(default=None, min_length=1, max_length=300)
    description: str | None = None
    priority: str | None = None
    due_date: datetime | None = None
    definition_of_done: str | None = None


class CreateTaskIn(BaseModel):
    title: str = Field(min_length=1, max_length=300)
    description: str | None = None
    # status lets the board's per-column "+" land the task in the right column (#82); omitted →
    # backlog (the service default). Leader Chat-with-Leader proposals still pass status=DRAFT
    # through the service call directly, not via this schema.
    status: str | None = None
    # A task is more than a title — capture the full definition the patron has in mind (#82).
    # priority is one of TaskPriority (critical/high/medium/low); anything else falls back to
    # medium in the service layer. assigned_marius_id seats the task on a project agent.
    priority: str | None = None
    due_date: datetime | None = None
    definition_of_done: str | None = None
    assigned_marius_id: UUID | None = None
    # The approved plan item this task belongs to (FR-027). Omitted → out of scope.
    plan_item_id: UUID | None = None
    created_by_user_id: str | None = None


class AssignIn(BaseModel):
    marius_id: UUID
    # A task has exactly one owner (FR-028). Putting a different worker on a task that
    # already has one is a **transfer**, and a transfer says why.
    transfer_reason: str | None = Field(default=None, max_length=2000)


class TransitionIn(BaseModel):
    status: str
    reason: str | None = None


class NextActionIn(BaseModel):
    next_action: str | None = None


class AnswerEscalationIn(BaseModel):
    """The patron's answer to a Mức 3 letter (FR-061a).

    `text` carries whichever words the chosen answer needs — the transfer reason, the new
    next action, or why the task is being dropped. One field rather than three because
    exactly one of them applies per answer, and three would invite sending two.
    """

    answer: Literal["reassign", "next_action", "cancel", "handled"]
    marius_id: UUID | None = None
    text: str | None = Field(default=None, max_length=2000)


class TaskOut(_Out):
    id: UUID
    project_id: UUID | None = None
    # Human-readable code "{project.key}-{seq}", e.g. "CALC-7" (minted at create).
    identifier: str | None = None
    title: str
    description: str | None = None
    status: str
    status_reason: str | None = None
    priority: str = "medium"
    due_date: datetime | None = None
    definition_of_done: str | None = None
    # spec 001 §6 — the four fields the board draws from (T069): what makes this task in
    # scope, what is moving it, whether the system dropped it, and who has signed off.
    plan_item_id: UUID | None = None
    drive: str | None = None
    # Which shape of that drive this is, when the kind covers more than one. `blocked_by_task`
    # is two different waits — behind another task, or behind a queue with no free machine —
    # and the screen has to tell them apart (FR-008a, FR-008b).
    drive_code: str | None = None
    stalled: bool = False
    # The stall verdict has the same two readers a refusal has: `stalled_reason` is the
    # server's English rendering, for an agent or anyone reading the raw response;
    # `stalled_reason_code` is what the screen builds the patron's own sentence from.
    stalled_reason: str | None = None
    stalled_reason_code: str | None = None
    # Filled by Story 3's two-signature rule; an empty list until then, never omitted, so
    # the board can render one shape whatever đợt it is talking to.
    signatures: list[dict[str, object]] = Field(default_factory=list)
    assigned_marius_id: UUID | None = None
    next_action: str | None = None
    # The two lifecycle marks (FR-015). The completion mark is what FR-031 requires a
    # finished task to carry — and it was being written to the database and then dropped
    # on the way out, so nothing outside the database could tell it had happened.
    in_progress_at: datetime | None = None
    completed_at: datetime | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None

    @model_validator(mode="after")
    def _split_the_stall_verdict(self) -> TaskOut:
        """The task stores one code; the wire carries both readings of it.

        Done here rather than at each of the eleven places that build a `TaskOut`, because
        a rendering one of them forgot is a screen showing `stall_run_active` to a patron.
        """
        if self.stalled_reason_code is None and self.stalled_reason is not None:
            self.stalled_reason_code = self.stalled_reason
            self.stalled_reason = stall_text_en(self.stalled_reason)
        return self


# ------------------------------------------------------------------ dependency
class AddDependencyIn(BaseModel):
    # This task is blocked_by `blocks_task_id` (it waits on that task to be done).
    blocks_task_id: UUID


class BlockerOut(_Out):
    """A task that blocks another (rendered in the blocked-by list)."""

    id: UUID
    identifier: str | None = None
    title: str
    status: str


class TaskDependencyEdgeOut(_Out):
    """A raw `blocked_by` edge (project board reads these to flag blocked cards)."""

    task_id: UUID
    blocks_task_id: UUID


class TaskCardCountsOut(_Out):
    """The tallies a board card draws that are not fields on the task row (T177).

    Its own route rather than four fields on ``TaskOut``: this is what a *board* needs,
    and ``TaskOut`` is also what a single-task read and the whole agent API return. Putting
    three grouped counts behind every one of those reads is a cost paid by callers that
    never draw a card.

    Only tasks with something to report appear. A task missing from the list has none of
    anything, which is the same thing the row would have said at the price of a row.
    """

    task_id: UUID
    comments: int = 0
    artifacts: int = 0
    criteria_total: int = 0
    criteria_passed: int = 0


# ---------------------------------------------------------------------- comment
class PostCommentIn(BaseModel):
    body: str = Field(min_length=1)
    author_kind: str = "human"
    author_user_id: str | None = None
    extra_mentions: list[UUID] = Field(default_factory=list)


class CommentOut(_Out):
    id: UUID
    task_id: UUID | None = None
    author_kind: str
    author_marius_id: UUID | None = None
    author_user_id: str | None = None
    body: str
    mentions: list[UUID]
    created_at: datetime | None = None


# --------------------------------------------------------------------- artifact
def decode_artifact_content(
    *,
    content_b64: str | None,
    content: str | None,
    content_sha256: str | None = None,
) -> bytes | None:
    """Resolve uploaded bytes for a `file` artifact (API_CONTRACT §7).

    Prefers base64 `content_b64` (decoded + optionally sha256-verified); falls back to raw
    text `content` for back-compat. Returns None when neither is present (e.g. a `link`).
    """
    if content_b64 is not None:
        try:
            raw = base64.b64decode(content_b64, validate=True)
        except (ValueError, base64.binascii.Error) as e:
            raise ValueError("content_b64 is not valid base64") from e
        if content_sha256 and hashlib.sha256(raw).hexdigest() != content_sha256:
            raise ValueError("content_sha256 does not match the uploaded bytes")
        return raw
    if content is not None:
        return content.encode("utf-8")
    return None


class PublishArtifactIn(BaseModel):
    name: str = Field(min_length=1, max_length=300)
    kind: str = "file"
    content_b64: str | None = None  # REQUIRED for kind="file" (decoded + sha256-verified)
    content: str | None = None  # legacy: raw text content (utf-8)
    content_sha256: str | None = None
    size_bytes: int | None = None
    uri: str | None = None  # REQUIRED for kind="link"


class ArtifactOut(_Out):
    id: UUID
    project_id: UUID | None = None
    task_id: UUID | None = None
    marius_id: UUID | None = None
    name: str
    kind: str
    uri: str
    stored: bool = False
    content_sha256: str | None = None
    size_bytes: int | None = None
    created_at: datetime | None = None

    @model_validator(mode="after")
    def _derive_stored(self) -> ArtifactOut:
        # file ⇒ bytes live in the bucket; link ⇒ external uri (not stored). (§7)
        self.stored = self.kind == "file"
        return self


# -------------------------------------------------------------------------- run
class WakeIn(BaseModel):
    marius_id: UUID
    reason: str | None = None


class WakeCauseOut(_Out):
    """One cause, as data. The interface holds the phrase table for both languages."""

    code: str
    params: dict[str, str] = Field(default_factory=dict)


class RunOut(_Out):
    id: UUID
    task_id: UUID | None = None
    marius_id: UUID | None = None
    adapter_type: str
    wake_source: str
    # Why this run was woken, twice over. `trigger_causes` is the record — a code and its
    # parameters, which the interface words in the reader's own language. `trigger_detail`
    # is the English rendering the agent's packet carried, kept as the fallback for runs
    # recorded before the codes existed (Constitution VII).
    trigger_causes: list[WakeCauseOut] = Field(default_factory=list)
    trigger_detail: str | None = None
    status: str
    external_run_id: str | None = None
    error: str | None = None
    next_action: str | None = None
    continuation_attempt: int = 0
    usage_json: dict = Field(default_factory=dict)
    started_at: datetime | None = None
    finished_at: datetime | None = None
    created_at: datetime | None = None


class RunEventOut(_Out):
    seq: int
    type: str
    payload: dict
    created_at: datetime | None = None


class RunStartedOut(BaseModel):
    run_id: UUID


# ------------------------------------------------------------------ agent-facing
class AgentCommentIn(BaseModel):
    body: str = Field(min_length=1)


class AgentArtifactIn(BaseModel):
    name: str = Field(min_length=1, max_length=300)
    kind: str = "file"
    content_b64: str | None = None
    content: str | None = None
    content_sha256: str | None = None
    uri: str | None = None


# ------------------------------------------------------------ Chat with Leader (#82)
class LeaderChatSendIn(BaseModel):
    message: str = Field(min_length=1, max_length=8000)


class LeaderChatOut(BaseModel):
    """Project-level Leader conversation + live, derived context (built from a
    ``LeaderChatView``, not an ORM row — leader_online/name are computed on read)."""

    project_id: UUID | None = None
    leader_marius_id: UUID | None = None
    leader_name: str | None = None
    leader_online: bool = False
    state: str = "idle"
    transcript: list[dict] = Field(default_factory=list)
    updated_at: datetime | None = None


class AgentCreateTaskIn(BaseModel):
    """The Leader's create-task tool payload (Chat-with-Leader, #82).

    `plan_item_id` is what decides whether the task goes live or waits for the patron
    (FR-027) — the Leader gets the list of approved items in its prompt."""

    title: str = Field(min_length=1, max_length=300)
    description: str | None = None
    assignee_marius_id: UUID | None = None
    plan_item_id: UUID | None = None


class AgentMajorChangeIn(BaseModel):
    """A change that widens what the patron agreed to (FR-075).

    ``area`` is a closed list on purpose. An open text field here would let the Leader
    describe an internal reshuffle as a "major change" and park work it was perfectly
    entitled to do — or the reverse, which is worse.
    """

    area: MajorChangeArea
    summary: str = Field(min_length=1, max_length=500)
    detail: str | None = None


class AgentRecoveryIn(BaseModel):
    """The recovery action the Leader decided at Level 2 (FR-059)."""

    action: str = Field(min_length=1, max_length=500)
    next_action: str | None = None


class AgentGiveUpIn(BaseModel):
    """The Leader saying a stalled task is beyond it (FR-059).

    Costs a reason, like every other piece of bad news in this system: the patron is about
    to be asked, and *why the Leader could not* is half of what they need to answer.
    """

    reason: str = Field(min_length=1, max_length=2000)


class ReopenTaskIn(BaseModel):
    """Bringing a closed task back always costs a reason (FR-022)."""

    reason: str = Field(min_length=1, max_length=2000)


class CriterionIn(BaseModel):
    text: str = Field(min_length=1, max_length=1000)


class SetCriteriaIn(BaseModel):
    """The whole yardstick, replaced in one move (FR-019)."""

    items: list[CriterionIn] = Field(default_factory=list)


class RateCriterionIn(BaseModel):
    """One criterion, scored against the output in review (Story 3 scenario 1).

    Only *passed* / *failed*: putting a criterion back to *unrated* is not a step in any
    scenario, and every extra state a caller can ask for is another path through the gate
    that has to be right.
    """

    result: Literal["passed", "failed"]
    # Required for a pass, refused for anything outside this task — enforced in the
    # domain and the use case respectively, not here, because both are rules about the
    # task rather than about the shape of the request.
    evidence_artifact_id: UUID | None = None


class CriterionOut(_Out):
    id: UUID
    task_id: UUID | None = None
    text: str
    order: int = 0
    result: str = "unrated"
    evidence_artifact_id: UUID | None = None


class AgentAssignmentRequestIn(BaseModel):
    """A worker asking to be put on a task — a request, never a claim (FR-072)."""

    note: str | None = Field(default=None, max_length=2000)


class AgentHandbackIn(BaseModel):
    """A worker handing work back or asking a clarifying question."""

    reason: str = Field(min_length=1, max_length=2000)


# ------------------------------------------------------------------ onboarding
# Agent-assisted project setup (Sprint 7 / Phase G). The Workspace Agent interviews the
# Patron; `finalize` materialises the accumulated plan into a Project + roster.
class OnboardingAnswerIn(BaseModel):
    """The Patron's answer to the pending question. ``answer`` is the picked option label(s)
    (multi-select joined with ', '); ``other_text`` carries a free-text ("Other") reply."""

    answer: str = Field(min_length=1, max_length=4000)
    other_text: str | None = Field(default=None, max_length=4000)


class OnboardingQuestionOptionIn(BaseModel):
    id: str = Field(min_length=1)
    label: str = Field(min_length=1)


class AgentOnboardingQuestionIn(BaseModel):
    """A live Workspace-Agent runtime posting its next question (agent-driven mode)."""

    question: str = Field(min_length=1, max_length=2000)
    options: list[OnboardingQuestionOptionIn] = Field(min_length=1)
    multi: bool = False


class OnboardingProjectDraftIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    objective: str = Field(min_length=1, max_length=4000)
    success_metrics: dict | None = None
    target_date: str | None = None
    context: str | None = Field(default=None, max_length=4000)


class OnboardingRosterRoleIn(BaseModel):
    title: str = Field(min_length=1, max_length=120)
    seats: int = Field(default=1, ge=1, le=20)
    is_leader: bool = False
    # BẮT BUỘC: quản gia phải nêu mỗi worker làm gì. Draft thiếu mô tả bất kỳ role nào ⇒ agent
    # nhận 422 rõ ràng ngay khi POST /agent/onboarding/{s}/complete (strict #112).
    description: str = Field(min_length=1, max_length=2000)
    skills: list[str] = Field(default_factory=list)


class AgentOnboardingCompleteIn(BaseModel):
    """A live WA posting its final project + roster draft for the Patron to confirm."""

    project: OnboardingProjectDraftIn
    roster: list[OnboardingRosterRoleIn] = Field(min_length=1)


class OnboardingOut(_Out):
    id: UUID
    workspace_id: UUID | None = None
    status: str
    transcript: list[dict] = Field(default_factory=list)
    collected: dict = Field(default_factory=dict)
    created_project_id: UUID | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None



# ------------------------------------------------- task log / inbox / thresholds
class TaskLogEntryOut(_Out):
    """One line of a task's history (spec 001 §10)."""

    id: UUID
    task_id: UUID | None = None
    seq: int
    kind: str
    actor_kind: str
    actor_marius_id: UUID | None = None
    actor_user_id: str | None = None
    before: str | None = None
    after: str | None = None
    reason: str | None = None
    detail: dict[str, object] = Field(default_factory=dict)
    created_at: datetime | None = None


class InboxItemOut(_Out):
    """A decision waiting on the calling patron (spec 001 §11)."""

    id: UUID
    workspace_id: UUID | None = None
    project_id: UUID | None = None
    task_id: UUID | None = None
    kind: str
    status: str
    title: str
    body: str | None = None
    reminder_tier: int = 0
    attempt_dossier: dict[str, object] = Field(default_factory=dict)
    created_at: datetime | None = None
    last_reminded_at: datetime | None = None
    resolved_at: datetime | None = None


class ThresholdsOut(_Out):
    """A project's effective timing thresholds — system floor plus its overrides."""

    hang_suspect_seconds: int
    hang_grace_seconds: int
    orchestration_cadence_seconds: int
    due_soon_hours: list[int]
    patron_reminder_hours: list[int]
    level1_recovery_attempts: int
    rejection_round_cap: int
    orchestration_wakes_per_hour: int
    orchestration_max_stretch: int
    orchestration_max_interval_seconds: int
    orchestration_min_interval_seconds: int
    level2_handover_attempts: int


class ThresholdsIn(BaseModel):
    """Per-project overrides. Every field optional — omit one to keep the system floor,
    and send an empty body to reset the project back to it entirely."""

    hang_suspect_seconds: int | None = Field(default=None, gt=0)
    hang_grace_seconds: int | None = Field(default=None, gt=0)
    orchestration_cadence_seconds: int | None = Field(default=None, gt=0)
    due_soon_hours: list[int] | None = None
    patron_reminder_hours: list[int] | None = None
    level1_recovery_attempts: int | None = Field(default=None, gt=0)
    rejection_round_cap: int | None = Field(default=None, gt=0)
    orchestration_wakes_per_hour: int | None = Field(default=None, gt=0)
    orchestration_max_stretch: int | None = Field(default=None, gt=0)
    orchestration_max_interval_seconds: int | None = Field(default=None, gt=0)
    orchestration_min_interval_seconds: int | None = Field(default=None, gt=0)
    level2_handover_attempts: int | None = Field(default=None, gt=0)


class SnagOut(_Out):
    """One thing the last sweep found on the board (spec 001 FR-052).

    The parts, not a finished sentence: the same snag is read by the Leader in its wake
    packet and by the patron on the board, and those two do not read the same language
    (Constitution VII). `detail` is the agent's English copy, kept for the audit record of
    what actually went out; the screen builds its own line from `kind` plus the fields
    beside it and never shows `detail`.
    """

    kind: str
    task_id: UUID
    identifier: str
    title: str = ""
    mark_hours: int | None = None
    detail: str


class OrchestrationOut(BaseModel):
    """The Leader's last look at this project's board (spec 001 FR-052 → FR-055).

    Deliberately reports the *sweep*, not a freshly computed list: what the board should
    show is what the orchestrator actually saw and acted on. A recomputed list would look
    right while the loop was dead — the exact confusion the sweep record exists to remove.
    """

    last_swept_at: datetime | None = None
    next_sweep_at: datetime | None = None
    interval_seconds: int = 0
    woke_leader: bool = False
    skipped_reason: str | None = None
    snags: list[SnagOut] = Field(default_factory=list)


# --------------------------------------------- project context / plan (spec 001)
class ProjectContextIn(BaseModel):
    """The five parts of the brief. All optional — an empty part reads as "không có"."""

    objective: str = ""
    background: str = ""
    constraints: str = ""
    scope: str = ""
    principles: str = ""


class ProjectContextOut(_Out):
    id: UUID
    project_id: UUID | None = None
    version: int
    objective: str = ""
    background: str = ""
    constraints: str = ""
    scope: str = ""
    principles: str = ""
    approval_status: str
    approved_at: datetime | None = None
    approved_by_user_id: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class ProjectContextViewOut(BaseModel):
    """What the patron sees: the version in force, plus one awaiting them if any."""

    approved: ProjectContextOut | None = None
    pending: ProjectContextOut | None = None


class ContextDecisionIn(BaseModel):
    approve: bool
    note: str | None = None


class PlanItemIn(BaseModel):
    title: str = Field(min_length=1, max_length=300)
    description: str = ""
    order: int = 0
    definition_of_done: str = ""
    depends_on: list[UUID] = Field(default_factory=list)


class PlanItemOut(_Out):
    id: UUID
    title: str
    description: str = ""
    order: int = 0
    definition_of_done: str = ""
    depends_on: list[UUID] = Field(default_factory=list)


class PlanIn(BaseModel):
    summary: str = ""
    risks: str = ""
    milestones: str = ""
    items: list[PlanItemIn] = Field(default_factory=list)


class PlanOut(_Out):
    id: UUID
    project_id: UUID | None = None
    version: int
    summary: str = ""
    risks: str = ""
    milestones: str = ""
    status: str
    patron_note: str | None = None
    submitted_at: datetime | None = None
    decided_at: datetime | None = None
    decided_by_user_id: str | None = None
    items: list[PlanItemOut] = Field(default_factory=list)
    created_at: datetime | None = None
    updated_at: datetime | None = None


class PlanDecisionIn(BaseModel):
    """The patron's three choices (FR-013). `note` is required for the last two."""

    decision: str
    note: str | None = None


class PhaseChangeIn(BaseModel):
    target_phase: str
    reason: str | None = None
