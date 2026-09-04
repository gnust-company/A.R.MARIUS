"""Repository interfaces (ports). Infrastructure implements these; the application
layer depends only on these abstractions."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Mapping, Sequence
from datetime import datetime
from uuid import UUID

from armarius.domain.entities.approval import Approval
from armarius.domain.entities.artifact import Artifact
from armarius.domain.entities.auto_approval import AutoApproval
from armarius.domain.entities.checklist_item import ChecklistItem, ChecklistTally
from armarius.domain.entities.comment import Comment
from armarius.domain.entities.inbox_item import InboxItem, InboxItemStatus
from armarius.domain.entities.label import Label
from armarius.domain.entities.leader_chat import ProjectLeaderConversation
from armarius.domain.entities.marius import Marius
from armarius.domain.entities.onboarding import OnboardingSession
from armarius.domain.entities.orchestration_sweep import OrchestrationSweep
from armarius.domain.entities.placement import Placement
from armarius.domain.entities.plan import Plan
from armarius.domain.entities.project_context import ProjectContext
from armarius.domain.entities.push_reason import TaskPushReason
from armarius.domain.entities.role import Role
from armarius.domain.entities.run import Run, RunEvent
from armarius.domain.entities.seat_grant import SeatGrant
from armarius.domain.entities.session import AgentTaskSession
from armarius.domain.entities.skill import Skill
from armarius.domain.entities.task import Task
from armarius.domain.entities.task_dependency import TaskDependency
from armarius.domain.entities.task_log import TaskLogEntry
from armarius.domain.entities.user import User
from armarius.domain.entities.wakeup import WakeupRequest
from armarius.domain.entities.workspace import Project, Workspace


class WorkspaceRepository(ABC):
    @abstractmethod
    async def add(self, workspace: Workspace) -> Workspace: ...
    @abstractmethod
    async def get(self, workspace_id: UUID) -> Workspace | None: ...
    @abstractmethod
    async def list(self) -> Sequence[Workspace]: ...
    @abstractmethod
    async def list_by_owner(self, owner_user_id: str) -> Sequence[Workspace]: ...
    @abstractmethod
    async def update(self, workspace: Workspace) -> Workspace: ...
    @abstractmethod
    async def remove(self, workspace_id: UUID) -> None:
        """Delete a workspace and every child it owns (projects + their roster/tasks,
        mariuses, skills, labels). No FK has ``ON DELETE CASCADE`` so the aggregate
        cascade is explicit — identical behaviour on SQLite and Postgres."""


class ProjectRepository(ABC):
    @abstractmethod
    async def add(self, project: Project) -> Project: ...
    @abstractmethod
    async def get(self, project_id: UUID) -> Project | None: ...
    @abstractmethod
    async def list_by_workspace(self, workspace_id: UUID) -> Sequence[Project]: ...
    @abstractmethod
    async def get_by_key(self, workspace_id: UUID, key: str) -> Project | None: ...
    @abstractmethod
    async def allocate_task_number(self, project_id: UUID) -> int:
        """Atomically increment + return the next per-project task sequence number.

        A single ``UPDATE … RETURNING`` so concurrent creates never share a number.
        """
    @abstractmethod
    async def update(self, project: Project) -> Project: ...
    @abstractmethod
    async def remove(self, project_id: UUID) -> None: ...


class RoleRepository(ABC):
    """Roster seats of a project (LLD §2.3)."""

    @abstractmethod
    async def add(self, role: Role) -> Role: ...
    @abstractmethod
    async def get(self, role_id: UUID) -> Role | None: ...
    @abstractmethod
    async def list_by_project(self, project_id: UUID) -> Sequence[Role]: ...
    @abstractmethod
    async def update(self, role: Role) -> Role: ...
    @abstractmethod
    async def remove(self, role_id: UUID) -> None: ...


class SeatGrantRepository(ABC):
    """System-only seat assignments (LLD §2.4, §3.3)."""

    @abstractmethod
    async def add(self, grant: SeatGrant) -> SeatGrant: ...
    @abstractmethod
    async def get(self, grant_id: UUID) -> SeatGrant | None: ...
    @abstractmethod
    async def list_by_project(self, project_id: UUID) -> Sequence[SeatGrant]: ...
    @abstractmethod
    async def remove(self, grant_id: UUID) -> None: ...


class ApprovalRepository(ABC):
    """Signatures on tasks — append-only (spec 001 §8, FR-033)."""

    @abstractmethod
    async def add(self, approval: Approval) -> Approval: ...
    @abstractmethod
    async def list_for_task(self, task_id: UUID) -> Sequence[Approval]: ...

    @abstractmethod
    async def list_for_tasks(
        self, task_ids: Sequence[UUID]
    ) -> Sequence[Approval]:
        """Signatures for many tasks at once, for readers that sweep a whole board.

        The orchestration cadence asks "is this task waiting on the Leader?" of every open
        task on every pass; one query per task turns a board into hundreds of round trips
        on a loop that never stops running.
        """

    @abstractmethod
    async def supersede_for_task(self, task_id: UUID) -> int:
        """Retire every signature this task still carries; return how many were retired.

        Called when the task goes back to being worked on. Nothing is deleted — the rows,
        their verdicts and their reasons all stay readable; they simply stop counting
        towards closing the deliverable that replaces the one they were given for.

        The only write on this repository that is not an insert, and it is a flag flip, so
        the "a signature you can edit is not evidence" rule still holds.

        The count is **advisory** — for logs and assertions, never for a branch. Some
        drivers do not promise an exact affected-row count on an UPDATE, and a caller that
        decided something on this number would be deciding on the driver.
        """


class AutoApprovalRepository(ABC):
    """One patron's auto-approval switch per project (spec 001 §5, FR-036)."""

    @abstractmethod
    async def get(self, project_id: UUID, user_id: str) -> AutoApproval | None: ...
    @abstractmethod
    async def set_enabled(
        self, project_id: UUID, user_id: str, *, enabled: bool
    ) -> AutoApproval: ...


class LabelRepository(ABC):
    """Workspace-scoped task tags (API_CONTRACT §5.4)."""

    @abstractmethod
    async def add(self, label: Label) -> Label: ...
    @abstractmethod
    async def list_by_workspace(self, workspace_id: UUID) -> Sequence[Label]: ...


class LeaderChatRepository(ABC):
    """Project-level Chat-with-Leader conversations (#82). One per project."""

    @abstractmethod
    async def add(
        self, conversation: ProjectLeaderConversation
    ) -> ProjectLeaderConversation: ...
    @abstractmethod
    async def get(self, conversation_id: UUID) -> ProjectLeaderConversation | None: ...
    @abstractmethod
    async def get_by_project(
        self, project_id: UUID
    ) -> ProjectLeaderConversation | None:
        """The single conversation for a project, or None if it was never opened."""
    @abstractmethod
    async def get_by_run(self, run_id: UUID) -> ProjectLeaderConversation | None:
        """The conversation whose current turn this run is taking, if it is taking one.

        Asked in this direction because that is the direction the news arrives from: a run
        carried out on somebody's machine reports itself finished, and all it names is
        itself. See ``ProjectLeaderConversation.driving_run_id``.
        """
    @abstractmethod
    async def update(
        self, conversation: ProjectLeaderConversation
    ) -> ProjectLeaderConversation: ...


class OnboardingRepository(ABC):
    """Agent-assisted project-setup chats (LLD §2.10, Sprint 7 / Phase G)."""

    @abstractmethod
    async def add(self, session: OnboardingSession) -> OnboardingSession: ...
    @abstractmethod
    async def get(self, session_id: UUID) -> OnboardingSession | None: ...
    @abstractmethod
    async def update(self, session: OnboardingSession) -> OnboardingSession: ...
    @abstractmethod
    async def list_by_workspace(
        self, workspace_id: UUID
    ) -> Sequence[OnboardingSession]:
        """All sessions for a workspace (newest first) — the active one is the first OPEN."""

    @abstractmethod
    async def get_by_run(self, run_id: UUID) -> OnboardingSession | None:
        """The chat whose current turn is this run, if the run is taking one.

        Asked when a run ends: an interview turn that finished without the agent saying
        anything leaves a chat with nobody driving it, and the patron is left watching a
        screen that will never move. The lookup goes this way round on purpose — see
        ``OnboardingSession.driving_run_id``.
        """


class MariusRepository(ABC):
    @abstractmethod
    async def add(self, marius: Marius) -> Marius: ...
    @abstractmethod
    async def get(self, marius_id: UUID) -> Marius | None: ...
    @abstractmethod
    async def list_by_workspace(self, workspace_id: UUID) -> Sequence[Marius]: ...
    @abstractmethod
    async def list_by_ids(self, marius_ids: list[UUID]) -> Sequence[Marius]: ...
    @abstractmethod
    async def update(self, marius: Marius) -> Marius: ...
    @abstractmethod
    async def remove(self, marius_id: UUID) -> None:
        """Delete a Marius and vacate any roster seats it held."""


class TaskRepository(ABC):
    @abstractmethod
    async def add(self, task: Task) -> Task: ...
    @abstractmethod
    async def get(self, task_id: UUID) -> Task | None: ...
    @abstractmethod
    async def list_by_project(
        self, project_id: UUID, *, statuses: list[str] | None = None
    ) -> Sequence[Task]: ...
    @abstractmethod
    async def update(self, task: Task) -> Task: ...

    @abstractmethod
    async def list_stall_candidates(
        self, now: datetime, *, limit: int = 500
    ) -> Sequence[Task]:
        """Every watched task the safety net has an opinion about (FR-057): its drive is
        missing, its drive is past its deadline, **or** it is currently flagged.

        That third clause is not padding. Without it the sweep can only ever raise alarms,
        never lower them: a flagged task that gets picked back up gains a live drive, drops
        out of the first two clauses, and keeps a red flag on the board forever. An alarm
        with no route back down is an alarm people learn to ignore.

        Tasks in a **closed** project are excluded (FR-005). Closing a project only moves
        one column on the project row; every open task it holds stays exactly where it was,
        so without this clause the net keeps flagging them and the recovery ladder keeps
        waking their workers — about a project the patron has declared finished.

        The one query the stall sweep runs, across every workspace, forever. It reads three
        indexed columns on `tasks` — which is the whole reason the drive's deadline lives on
        the task row rather than beside the ladder state — plus one existence check against
        `projects` for the phase.

        ``limit`` bounds one pass, not the problem: a service that comes up to ten thousand
        dropped tasks should raise the first few hundred alarms now and the rest next tick,
        rather than hold a transaction open over the entire table.
        """

    @abstractmethod
    async def list_open(self, *, limit: int = 1000) -> Sequence[Task]:
        """Every watched task outside a closed project, drive or no drive. Used once at
        startup to rebuild drives from the last durable state (FR-068), never on the hot
        path. Closed projects are skipped for the same reason as the sweep: rebuilding a
        drive for a task nobody will ever be woken about is work done to no end, and it
        puts that task back in the net's sights."""


class TaskPushReasonRepository(ABC):
    """The recovery ladder standing on a task (spec 001 §9, FR-059 → FR-061).

    Keyed by task, one row at most — ``upsert`` rather than add/update because the caller
    never cares whether a ladder already existed, only where it stands now.
    """

    @abstractmethod
    async def get_for_task(self, task_id: UUID) -> TaskPushReason | None: ...

    @abstractmethod
    async def upsert(self, reason: TaskPushReason) -> TaskPushReason: ...

    @abstractmethod
    async def clear_for_task(self, task_id: UUID) -> None:
        """Drop the ladder — the task recovered, or closed. Silent when there is none."""

    @abstractmethod
    async def list_for_tasks(self, task_ids: Sequence[UUID]) -> Sequence[TaskPushReason]:
        """One query for a whole batch. The stall sweep reads ladders for the handful of
        tasks its cheap scan flagged, and doing that one round trip per task would put a
        fan-out on a loop that never stops."""


class ChecklistItemRepository(ABC):
    """Acceptance criteria — the yardstick a task is measured against (FR-019).

    Whole-list replacement rather than per-row edits: the criteria are read as one
    yardstick, and swapping the list in one move means nobody can ever see half of an
    edit while approving against it."""

    @abstractmethod
    async def list_by_task(self, task_id: UUID) -> Sequence[ChecklistItem]: ...
    @abstractmethod
    async def count_by_project(
        self, project_id: UUID
    ) -> Mapping[UUID, ChecklistTally]: ...
    @abstractmethod
    async def replace_for_task(
        self, task_id: UUID, items: Sequence[ChecklistItem]
    ) -> Sequence[ChecklistItem]: ...
    @abstractmethod
    async def update(self, item: ChecklistItem) -> ChecklistItem: ...


class TaskDependencyRepository(ABC):
    """`blocked_by` edges. Feeds the dependency-gate (a task cannot enter
    todo/in_progress while any task it is blocked_by is unfinished)."""

    @abstractmethod
    async def add(self, dependency: TaskDependency) -> TaskDependency: ...
    @abstractmethod
    async def remove(self, task_id: UUID, blocks_task_id: UUID) -> None: ...
    @abstractmethod
    async def get(
        self, task_id: UUID, blocks_task_id: UUID
    ) -> TaskDependency | None: ...
    @abstractmethod
    async def list_blockers(self, task_id: UUID) -> Sequence[TaskDependency]:
        """Edges where `task_id` is the blocked task (its `blocked_by` list)."""
    @abstractmethod
    async def list_dependents(self, task_id: UUID) -> Sequence[TaskDependency]:
        """The mirror: edges where `task_id` is the blocker — who is waiting on it.

        Read when a task finishes, to work out what it just freed (FR-031)."""
    @abstractmethod
    async def list_by_project(self, project_id: UUID) -> Sequence[TaskDependency]:
        """All edges whose blocked task lives in this project (board view)."""
    @abstractmethod
    async def list_unfinished_blockers(self, task_id: UUID) -> Sequence[Task]:
        """The blockers that have not finished yet — named, so a refusal can say which."""
    @abstractmethod
    async def all_blockers_done(self, task_id: UUID) -> bool:
        """True when every task `task_id` is blocked_by has status `done`
        (vacuously true when it has no blockers)."""


class CommentRepository(ABC):
    @abstractmethod
    async def add(self, comment: Comment) -> Comment: ...
    @abstractmethod
    async def list_by_task(self, task_id: UUID) -> Sequence[Comment]: ...
    @abstractmethod
    async def count_by_project(self, project_id: UUID) -> Mapping[UUID, int]: ...
    @abstractmethod
    async def list_since(self, task_id: UUID, after_seq: int) -> Sequence[Comment]: ...


class SessionRepository(ABC):
    @abstractmethod
    async def get_for(
        self, marius_id: UUID, adapter_type: str, task_id: UUID
    ) -> AgentTaskSession | None: ...
    @abstractmethod
    async def upsert(self, session: AgentTaskSession) -> AgentTaskSession: ...
    @abstractmethod
    async def delete(self, session_id: UUID) -> None: ...


class RunRepository(ABC):
    @abstractmethod
    async def add(self, run: Run) -> Run: ...
    @abstractmethod
    async def get(self, run_id: UUID) -> Run | None: ...
    @abstractmethod
    async def update(self, run: Run) -> Run: ...
    @abstractmethod
    async def list_by_task(self, task_id: UUID) -> Sequence[Run]: ...
    @abstractmethod
    async def list_by_marius(self, marius_id: UUID) -> Sequence[Run]: ...

    @abstractmethod
    async def get_active_for(self, marius_id: UUID, task_id: UUID) -> Run | None:
        """The run currently holding this (agent, task) pair, if any (FR-050).

        There can be at most one — a partial unique index guarantees it — so the answer is
        a single run rather than a list.
        """

    @abstractmethod
    async def task_ids_with_active_run(
        self, task_ids: Sequence[UUID]
    ) -> set[UUID]:
        """Which of these tasks have someone mid-run. Same question as
        ``has_active_for_task``, asked once for a whole board."""

    @abstractmethod
    async def list_silent_active(
        self, silent_since: datetime, *, limit: int = 200
    ) -> Sequence[Run]:
        """Runs still marked live that have emitted nothing since ``silent_since`` (FR-062).

        Asked across every workspace at once, because a hung run is a property of the run
        and not of any project: walking projects to find them would make the reaper's cost
        scale with the number of projects rather than with the number of sick runs.
        """

    @abstractmethod
    async def has_active_for_task(self, task_id: UUID) -> bool:
        """Whether *anyone* is mid-run on this task.

        Deliberately not "the assignee's run": a run outlives a reassignment, and the
        orchestrator's question is whether the task is being worked on at all (FR-052),
        not by whom. Asking about the current assignee would call an unassigned task idle
        while an agent was still finishing a turn on it.
        """


class RunEventRepository(ABC):
    @abstractmethod
    async def add(self, event: RunEvent) -> RunEvent: ...
    @abstractmethod
    async def list_by_run(
        self,
        run_id: UUID,
        *,
        types: Sequence[str] | None = None,
        after_seq: int | None = None,
        limit: int | None = None,
    ) -> Sequence[RunEvent]:
        """A run's events in order, narrowed the three ways a reader narrows them.

        `types` is the filter that makes a thousand-line log usable — finding one tool call
        among them by eye is not finding it (FR-052). `after_seq` and `limit` are how a screen
        walks a long run without asking for all of it at once, and they work on `seq` rather
        than on an offset because `seq` is the run's own ordering and does not shift when a
        late batch lands in the middle of one.
        """
        ...

    @abstractmethod
    async def forget_before(self, cutoff: datetime) -> int:
        """Drop every event older than `cutoff`, and everything kept apart from them.

        Counted from the event's own clock, so what is forgotten is decided by when the thing
        happened and not by when a row was written (FR-050). An event with no clock at all is
        never swept: there is no answer to *how old is it*, and guessing one would quietly
        delete the rows this system knows least about.
        """
        ...

    @abstractmethod
    async def full_text(self, run_id: UUID, seq: int) -> tuple[str, str, int] | None:
        """The whole of what event `seq` only carries the opening of: field, text, size.

        None when that event has nothing kept apart — which is the ordinary case, and is not
        an error: it means the payload already holds the whole thing.
        """
        ...


class ArtifactRepository(ABC):
    @abstractmethod
    async def add(self, artifact: Artifact) -> Artifact: ...
    @abstractmethod
    async def list_by_task(self, task_id: UUID) -> Sequence[Artifact]: ...
    @abstractmethod
    async def find_by_dedup_key(
        self, task_id: UUID, logical_name: str, content_hash: str
    ) -> Artifact | None:
        """The row a retried publish should land on instead of duplicating (FR-020c)."""
    @abstractmethod
    async def count_named(self, task_id: UUID, logical_name: str) -> int:
        """How many versions of this name the task already holds — the next version's
        number is this plus one."""
    @abstractmethod
    async def count_by_task(self, task_id: UUID) -> int: ...
    @abstractmethod
    async def count_by_project(self, project_id: UUID) -> Mapping[UUID, int]: ...


class WakeupRepository(ABC):
    @abstractmethod
    async def add(self, wakeup: WakeupRequest) -> WakeupRequest: ...
    @abstractmethod
    async def update(self, wakeup: WakeupRequest) -> WakeupRequest: ...
    @abstractmethod
    async def list_active_for(
        self, marius_id: UUID, task_id: UUID
    ) -> Sequence[WakeupRequest]: ...

    @abstractmethod
    async def get_for_run(self, run_id: UUID) -> WakeupRequest | None:
        """The wake this run was opened for, if one was written down.

        Read when a run changes hands: a run that is not about a task cannot have its
        message built from one, so the message it was queued with is what it is given
        (see ``WakeEngine.compose_packet``).
        """

    @abstractmethod
    async def list_pending_for_task(self, task_id: UUID) -> Sequence[WakeupRequest]:
        """Every wake still owed on this task, whoever it is addressed to.

        The safety net's question is whether *anything* is booked to touch this task,
        not whether one particular agent has a wake pending — a task can be reassigned
        between the booking and the sweep, and asking about the current assignee would
        call it dropped while the old assignee's wake was still queued.
        """

    @abstractmethod
    async def list_coalesced_into(self, run_id: UUID) -> Sequence[WakeupRequest]:
        """Every cause that was folded into this run, oldest first.

        Read when the run ends: a cause that arrived after the prompt was built was never
        shown to the agent, so the system still owes it a wake (FR-050).
        """


class OrchestrationSweepRepository(ABC):
    """Append-only record of the orchestration cadence (spec 001 FR-052 → FR-055).

    No ``update`` and no ``remove``: a sweep is something that happened. Reads are all the
    same shape — the project's most recent sweeps, newest first — because the three
    questions the loop asks (when did I last look, how long has this been quiet, how many
    wakes have I spent this hour) are all answered from the same short window.
    """

    @abstractmethod
    async def add(self, sweep: OrchestrationSweep) -> OrchestrationSweep: ...

    @abstractmethod
    async def list_recent(
        self, project_id: UUID, *, limit: int = 32
    ) -> Sequence[OrchestrationSweep]:
        """Newest first. A bounded look back for questions counted in *sweeps* — the
        quiet streak that earns a project its slack, and the deadline marks already
        announced. Never for questions counted in *time*: see below."""

    @abstractmethod
    async def count_wakes_since(self, project_id: UUID, since: datetime) -> int:
        """How many cadence wakes this project has spent since a moment in time.

        Its own query rather than a filter over ``list_recent``, because the hourly
        ceiling (FR-055) is a question about **time** and a row limit answers a question
        about **rows**. Filtering N fetched rows by timestamp makes the real window
        ``min(N sweeps, one hour)``: on a project with a short cadence, N sweeps stop
        covering an hour, older wakes drop out of the count, and the ceiling silently
        lifts — worst on exactly the busy projects it exists to protect.
        """


class SkillRepository(ABC):
    """Repository for Skill entities (workspace-scoped Skill Shop)."""

    @abstractmethod
    async def add(self, skill: Skill) -> Skill: ...
    @abstractmethod
    async def get(self, skill_id: UUID) -> Skill | None: ...
    @abstractmethod
    async def update(self, skill: Skill) -> Skill: ...
    @abstractmethod
    async def list_by_workspace(self, workspace_id: UUID) -> Sequence[Skill]: ...
    @abstractmethod
    async def get_by_slug(self, workspace_id: UUID, slug: str) -> Skill | None: ...
    @abstractmethod
    async def list_by_ids(self, skill_ids: list[UUID]) -> Sequence[Skill]: ...
    @abstractmethod
    async def remove(self, skill_id: UUID) -> None: ...


class UserRepository(ABC):
    """Repository for User entities (human users)."""

    @abstractmethod
    async def add(self, user: User) -> User: ...

    @abstractmethod
    async def get(self, user_id: UUID) -> User | None: ...

    @abstractmethod
    async def get_by_email(self, email: str) -> User | None: ...

    @abstractmethod
    async def get_by_username(self, username: str) -> User | None: ...

    @abstractmethod
    async def update(self, user: User) -> User: ...

    @abstractmethod
    async def list(self) -> Sequence[User]: ...


class TaskLogRepository(ABC):
    """Append-only task history (spec 001 §10).

    Deliberately has no ``update`` and no ``remove``: a correction is a new entry, never
    a rewrite. Anything that needs to change history is asking the wrong question.
    """

    @abstractmethod
    async def append(self, entry: TaskLogEntry) -> TaskLogEntry: ...

    @abstractmethod
    async def next_seq(self, task_id: UUID) -> int: ...

    @abstractmethod
    async def list_by_task(self, task_id: UUID) -> Sequence[TaskLogEntry]: ...


class InboxRepository(ABC):
    """Patron inbox items (spec 001 §11)."""

    @abstractmethod
    async def add(self, item: InboxItem) -> InboxItem: ...

    @abstractmethod
    async def get(self, item_id: UUID) -> InboxItem | None: ...

    @abstractmethod
    async def update(self, item: InboxItem) -> InboxItem: ...

    @abstractmethod
    async def list_for_recipient(
        self,
        recipient_user_id: str,
        *,
        status: InboxItemStatus | None = None,
        project_id: UUID | None = None,
    ) -> Sequence[InboxItem]: ...

    @abstractmethod
    async def list_pending_for_task(self, task_id: UUID) -> Sequence[InboxItem]: ...

    @abstractmethod
    async def list_pending_for_project(self, project_id: UUID) -> Sequence[InboxItem]:
        """Every item still waiting on this project, whoever it was addressed to.

        Not scoped to a recipient, unlike the patron-facing reads: closing a project has
        to clear what it leaves behind for *everyone* it ever asked, and the closer is not
        always the patron who was asked.
        """

    @abstractmethod
    async def list_pending(self, *, limit: int = 500) -> Sequence[InboxItem]:
        """Every item still waiting, across every workspace, oldest first (FR-065).

        The reminder ladder's one query. Not scoped to a recipient on purpose: the
        question is 'what has been waiting too long', and asking it per patron would
        make the loop's cost scale with the number of patrons rather than with the
        number of things actually overdue.
        """


class ProjectContextRepository(ABC):
    """Versioned project brief (spec 001 §2)."""

    @abstractmethod
    async def add(self, context: ProjectContext) -> ProjectContext: ...

    @abstractmethod
    async def update(self, context: ProjectContext) -> ProjectContext: ...

    @abstractmethod
    async def get_approved(self, project_id: UUID) -> ProjectContext | None: ...

    @abstractmethod
    async def get_pending(self, project_id: UUID) -> ProjectContext | None: ...

    @abstractmethod
    async def latest_version(self, project_id: UUID) -> int: ...


class PlanRepository(ABC):
    """Project plan and its items (spec 001 §3). Items ride with their plan."""

    @abstractmethod
    async def add(self, plan: Plan) -> Plan: ...

    @abstractmethod
    async def update(self, plan: Plan) -> Plan: ...

    @abstractmethod
    async def get(self, plan_id: UUID) -> Plan | None: ...

    @abstractmethod
    async def get_current(self, project_id: UUID) -> Plan | None: ...

    @abstractmethod
    async def get_approved(self, project_id: UUID) -> Plan | None: ...

    @abstractmethod
    async def latest_version(self, project_id: UUID) -> int: ...


class PlacementRepository(ABC):
    """Where agents are put to work, and which agent was put where (FR-007, FR-007f).

    There is no method here that moves an agent, and that absence is the rule rather than an
    oversight: FR-007 says the attachment is fixed for life, and a port with a `move` on it
    is a port someone will eventually call. The one way to change where an agent works is to
    retire it and create another — a decision that belongs to a person.
    """

    @abstractmethod
    async def get(self, workspace_id: UUID, placement_id: UUID) -> Placement | None:
        """One placement, or None when it is not there **or not this workspace's**.

        The two collapse on purpose. Telling them apart would let a caller confirm that an
        id exists somewhere they cannot see (Constitution I).
        """

    @abstractmethod
    async def attach(self, marius_id: UUID, workspace_id: UUID, placement_id: UUID) -> None:
        """Put an agent at a placement, once. Refuses an agent that already has one."""

    @abstractmethod
    async def placed_at(self, marius_ids: Sequence[UUID]) -> Mapping[UUID, Placement]:
        """Where each of these agents was put, as the place stands **right now**.

        Different question from `get`, and the difference is the whole point. `get` answers
        whether a placement is configured to take work — the question asked once, when
        somebody is choosing where to put a new agent. This one answers whether it can take
        work at this moment, which folds in everything that can go wrong after the choice
        was made. A placement that was open yesterday and is shut today comes back shut.

        An id missing from the answer was never placed at all. That is not an error and
        not an empty success: an agent with nowhere to work is offline, which is a state
        with a defined meaning rather than a silence (FR-007f).

        Asked in bulk because the two callers ask about a whole roster at once, and because
        the verdict and the reason must be computed in the same breath — a screen saying
        why an agent is offline while the engine still calls it online is worse than either
        answer alone (FR-006a, FR-006c).
        """
