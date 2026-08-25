"""In-memory fakes of the application ports — drive use cases without SQLAlchemy.

A single `_Store` is shared across every `FakeUnitOfWork` a `FakeUowFactory` hands out,
so writes committed in one UoW are visible to the next (mirroring a real DB across
transactions). `commit`/`rollback` are no-ops: repos mutate the shared store directly.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from types import TracebackType
from uuid import UUID, uuid4

from armarius.application.ports.adapter import (
    AdapterCapabilities,
    Diagnostics,
    ExecResult,
    MariusAdapter,
)
from armarius.application.ports.liveness_probe import LivenessProbe
from armarius.application.ports.unit_of_work import UnitOfWork
from armarius.domain.entities.approval import Approval
from armarius.domain.entities.auto_approval import AutoApproval
from armarius.domain.entities.checklist_item import ChecklistItem
from armarius.domain.entities.inbox_item import InboxItem, InboxItemStatus
from armarius.domain.entities.label import Label
from armarius.domain.entities.marius import Marius
from armarius.domain.entities.onboarding import OnboardingSession
from armarius.domain.entities.placement import Placement
from armarius.domain.entities.push_reason import TaskPushReason
from armarius.domain.entities.role import Role
from armarius.domain.entities.run import ACTIVE_RUN_STATUSES, Run, RunStatus
from armarius.domain.entities.seat_grant import SeatGrant
from armarius.domain.entities.skill import Skill
from armarius.domain.entities.task import Task, TaskStatus
from armarius.domain.entities.task_dependency import TaskDependency
from armarius.domain.entities.task_log import TaskLogEntry
from armarius.domain.entities.workspace import Project, ProjectStatus, Workspace
from armarius.domain.services.push_reason_rules import watches
from armarius.shared.errors import Conflict, NotFound


@dataclass
class _Store:
    workspaces: dict[UUID, Workspace] = field(default_factory=dict)
    labels: dict[UUID, Label] = field(default_factory=dict)
    onboardings: dict[UUID, OnboardingSession] = field(default_factory=dict)
    projects: dict[UUID, Project] = field(default_factory=dict)
    tasks: dict[UUID, Task] = field(default_factory=dict)
    criteria: dict[UUID, ChecklistItem] = field(default_factory=dict)
    task_logs: dict[UUID, TaskLogEntry] = field(default_factory=dict)
    push_reasons: dict[UUID, TaskPushReason] = field(default_factory=dict)
    runs: dict[UUID, Run] = field(default_factory=dict)
    inbox: dict[UUID, InboxItem] = field(default_factory=dict)
    dependencies: dict[UUID, TaskDependency] = field(default_factory=dict)
    roles: dict[UUID, Role] = field(default_factory=dict)
    seat_grants: dict[UUID, SeatGrant] = field(default_factory=dict)
    approvals: list[Approval] = field(default_factory=list)
    auto_approvals: dict[tuple[UUID, str], AutoApproval] = field(default_factory=dict)
    mariuses: dict[UUID, Marius] = field(default_factory=dict)
    placements: dict[UUID, Placement] = field(default_factory=dict)
    attachments: dict[UUID, UUID] = field(default_factory=dict)
    skills: dict[UUID, Skill] = field(default_factory=dict)


class _FakeWorkspaceRepo:
    def __init__(self, store: _Store) -> None:
        self._s = store

    async def add(self, ws: Workspace) -> Workspace:
        self._s.workspaces[ws.id] = ws
        return ws

    async def get(self, workspace_id: UUID) -> Workspace | None:
        return self._s.workspaces.get(workspace_id)

    async def list(self) -> list[Workspace]:
        return list(self._s.workspaces.values())

    async def list_by_owner(self, owner_user_id: str) -> list[Workspace]:
        return [w for w in self._s.workspaces.values() if w.owner_user_id == owner_user_id]

    async def update(self, ws: Workspace) -> Workspace:
        if ws.id not in self._s.workspaces:
            raise LookupError("workspace not found")
        self._s.workspaces[ws.id] = ws
        return ws


class _FakeLabelRepo:
    def __init__(self, store: _Store) -> None:
        self._s = store

    async def add(self, label: Label) -> Label:
        self._s.labels[label.id] = label
        return label

    async def list_by_workspace(self, workspace_id: UUID) -> list[Label]:
        return [x for x in self._s.labels.values() if x.workspace_id == workspace_id]


class _FakeTaskRepo:
    def __init__(self, store: _Store) -> None:
        self._s = store

    async def add(self, task: Task) -> Task:
        self._s.tasks[task.id] = task
        return task

    async def get(self, task_id: UUID) -> Task | None:
        return self._s.tasks.get(task_id)

    async def list_by_project(
        self, project_id: UUID, *, statuses: list[str] | None = None
    ) -> list[Task]:
        items = [t for t in self._s.tasks.values() if t.project_id == project_id]
        if statuses:
            items = [t for t in items if str(t.status) in statuses]
        return items

    async def update(self, task: Task) -> Task:
        self._s.tasks[task.id] = task
        return task

    def _in_a_closed_project(self, task: Task) -> bool:
        """FR-005 — mirrors the SQL scans' phase clause. A task whose project is missing
        from the store counts as live, exactly as NOT EXISTS treats it."""
        project = self._s.projects.get(task.project_id) if task.project_id else None
        return project is not None and project.status is ProjectStatus.CLOSED

    async def list_stall_candidates(
        self, now: datetime, *, limit: int = 500
    ) -> list[Task]:
        return [
            t
            for t in self._s.tasks.values()
            if watches(t.status)
            and not self._in_a_closed_project(t)
            and (
                t.drive is None
                or (t.drive_expires_at is not None and t.drive_expires_at <= now)
                or t.stalled
            )
        ][:limit]

    async def list_open(self, *, limit: int = 1000) -> list[Task]:
        return [
            t
            for t in self._s.tasks.values()
            if watches(t.status) and not self._in_a_closed_project(t)
        ][:limit]


class _FakeRunRepo:
    """Enough of the run repository for the loops that read it (liveness reaper, sweeps)."""

    def __init__(self, store: _Store) -> None:
        self._s = store

    async def add(self, run: Run) -> Run:
        self._s.runs[run.id] = run
        return run

    async def get(self, run_id: UUID) -> Run | None:
        return self._s.runs.get(run_id)

    async def update(self, run: Run) -> Run:
        self._s.runs[run.id] = run
        return run

    async def list_by_task(self, task_id: UUID) -> list[Run]:
        return [r for r in self._s.runs.values() if r.task_id == task_id]

    async def list_by_marius(self, marius_id: UUID) -> list[Run]:
        return [r for r in self._s.runs.values() if r.marius_id == marius_id]

    async def get_active_for(self, marius_id: UUID, task_id: UUID) -> Run | None:
        for r in self._s.runs.values():
            if (
                r.marius_id == marius_id
                and r.task_id == task_id
                and r.status in ACTIVE_RUN_STATUSES
            ):
                return r
        return None

    async def task_ids_with_active_run(self, task_ids) -> set[UUID]:  # noqa: ANN001
        wanted = set(task_ids)
        return {
            r.task_id
            for r in self._s.runs.values()
            if r.task_id in wanted and r.status in ACTIVE_RUN_STATUSES and r.task_id
        }

    async def has_active_for_task(self, task_id: UUID) -> bool:
        return any(
            r.task_id == task_id and r.status in ACTIVE_RUN_STATUSES
            for r in self._s.runs.values()
        )

    async def list_silent_active(
        self, silent_since: datetime, *, limit: int = 200
    ) -> list[Run]:
        out = [
            r
            for r in self._s.runs.values()
            if r.status in ACTIVE_RUN_STATUSES
            and (stamp := (r.last_output_at or r.started_at or r.created_at)) is not None
            and stamp <= silent_since
        ]
        return out[:limit]


class _FakeTaskPushReasonRepo:
    def __init__(self, store: _Store) -> None:
        self._s = store

    async def get_for_task(self, task_id: UUID) -> TaskPushReason | None:
        return self._s.push_reasons.get(task_id)

    async def upsert(self, reason: TaskPushReason) -> TaskPushReason:
        assert reason.task_id is not None
        self._s.push_reasons[reason.task_id] = reason
        return reason

    async def clear_for_task(self, task_id: UUID) -> None:
        self._s.push_reasons.pop(task_id, None)

    async def list_for_tasks(self, task_ids) -> list[TaskPushReason]:  # noqa: ANN001
        wanted = set(task_ids)
        return [r for tid, r in self._s.push_reasons.items() if tid in wanted]


class _FakeChecklistItemRepo:
    def __init__(self, store: _Store) -> None:
        self._s = store

    async def list_by_task(self, task_id: UUID) -> list[ChecklistItem]:
        items = [i for i in self._s.criteria.values() if i.task_id == task_id]
        items.sort(key=lambda i: i.order)
        return items

    async def replace_for_task(
        self, task_id: UUID, items: list[ChecklistItem]
    ) -> list[ChecklistItem]:
        for iid in [i.id for i in self._s.criteria.values() if i.task_id == task_id]:
            self._s.criteria.pop(iid, None)
        for item in items:
            item.task_id = task_id
            self._s.criteria[item.id] = item
        return list(items)

    async def update(self, item: ChecklistItem) -> ChecklistItem:
        self._s.criteria[item.id] = item
        return item


class _FakeTaskDependencyRepo:
    def __init__(self, store: _Store) -> None:
        self._s = store

    async def add(self, dependency: TaskDependency) -> TaskDependency:
        self._s.dependencies[dependency.id] = dependency
        return dependency

    async def remove(self, task_id: UUID, blocks_task_id: UUID) -> None:
        for dep_id, d in list(self._s.dependencies.items()):
            if d.task_id == task_id and d.blocks_task_id == blocks_task_id:
                del self._s.dependencies[dep_id]

    async def get(
        self, task_id: UUID, blocks_task_id: UUID
    ) -> TaskDependency | None:
        return next(
            (
                d
                for d in self._s.dependencies.values()
                if d.task_id == task_id and d.blocks_task_id == blocks_task_id
            ),
            None,
        )

    async def list_blockers(self, task_id: UUID) -> list[TaskDependency]:
        return [d for d in self._s.dependencies.values() if d.task_id == task_id]

    async def list_dependents(self, task_id: UUID) -> list[TaskDependency]:
        return [d for d in self._s.dependencies.values() if d.blocks_task_id == task_id]

    async def list_by_project(self, project_id: UUID) -> list[TaskDependency]:
        out = []
        for d in self._s.dependencies.values():
            blocked = self._s.tasks.get(d.task_id) if d.task_id else None
            if blocked is not None and blocked.project_id == project_id:
                out.append(d)
        return out

    async def list_unfinished_blockers(self, task_id: UUID) -> list[Task]:
        out = []
        for d in self._s.dependencies.values():
            if d.task_id != task_id or d.blocks_task_id is None:
                continue
            blocker = self._s.tasks.get(d.blocks_task_id)
            if blocker is not None and blocker.status != TaskStatus.DONE:
                out.append(blocker)
        return out

    async def all_blockers_done(self, task_id: UUID) -> bool:
        for d in self._s.dependencies.values():
            if d.task_id != task_id:
                continue
            blocker = self._s.tasks.get(d.blocks_task_id) if d.blocks_task_id else None
            if blocker is None or blocker.status != TaskStatus.DONE:
                return False
        return True


class _FakeProjectRepo:
    def __init__(self, store: _Store) -> None:
        self._s = store

    async def add(self, project: Project) -> Project:
        self._s.projects[project.id] = project
        return project

    async def get(self, project_id: UUID) -> Project | None:
        return self._s.projects.get(project_id)

    async def list_by_workspace(self, workspace_id: UUID) -> list[Project]:
        return [p for p in self._s.projects.values() if p.workspace_id == workspace_id]

    async def get_by_key(self, workspace_id: UUID, key: str) -> Project | None:
        return next(
            (
                p
                for p in self._s.projects.values()
                if p.workspace_id == workspace_id and p.key == key
            ),
            None,
        )

    async def allocate_task_number(self, project_id: UUID) -> int:
        project = self._s.projects.get(project_id)
        if project is None:
            raise LookupError("project not found")
        # `next_task_seq` is the NEXT number to assign (starts at 1); claim it then advance.
        claimed = project.next_task_seq
        project.next_task_seq = claimed + 1
        return claimed

    async def update(self, project: Project) -> Project:
        self._s.projects[project.id] = project
        return project

    async def remove(self, project_id: UUID) -> None:
        # Mirror the SQL aggregate cascade: drop the project's roles + seat grants too.
        self._s.projects.pop(project_id, None)
        for rid in [r.id for r in self._s.roles.values() if r.project_id == project_id]:
            self._s.roles.pop(rid, None)
        for gid in [
            g.id for g in self._s.seat_grants.values() if g.project_id == project_id
        ]:
            self._s.seat_grants.pop(gid, None)


class _FakeRoleRepo:
    def __init__(self, store: _Store) -> None:
        self._s = store

    async def add(self, role: Role) -> Role:
        self._s.roles[role.id] = role
        return role

    async def get(self, role_id: UUID) -> Role | None:
        return self._s.roles.get(role_id)

    async def list_by_project(self, project_id: UUID) -> list[Role]:
        return [r for r in self._s.roles.values() if r.project_id == project_id]

    async def update(self, role: Role) -> Role:
        self._s.roles[role.id] = role
        return role

    async def remove(self, role_id: UUID) -> None:
        self._s.roles.pop(role_id, None)


class _FakeSeatGrantRepo:
    def __init__(self, store: _Store) -> None:
        self._s = store

    async def add(self, grant: SeatGrant) -> SeatGrant:
        self._s.seat_grants[grant.id] = grant
        return grant

    async def get(self, grant_id: UUID) -> SeatGrant | None:
        return self._s.seat_grants.get(grant_id)

    async def list_by_project(self, project_id: UUID) -> list[SeatGrant]:
        return [g for g in self._s.seat_grants.values() if g.project_id == project_id]

    async def remove(self, grant_id: UUID) -> None:
        if self._s.seat_grants.pop(grant_id, None) is None:
            raise NotFound("seat_grant_not_found")


class _FakeApprovalRepo:
    def __init__(self, store: _Store) -> None:
        self._s = store

    async def add(self, approval: Approval) -> Approval:
        self._s.approvals.append(approval)
        return approval

    async def list_for_task(self, task_id: UUID) -> list[Approval]:
        return [a for a in self._s.approvals if a.task_id == task_id]

    async def list_for_tasks(self, task_ids: Sequence[UUID]) -> list[Approval]:
        wanted = set(task_ids)
        return [a for a in self._s.approvals if a.task_id in wanted]

    async def supersede_for_task(self, task_id: UUID) -> int:
        retired = 0
        for a in self._s.approvals:
            if a.task_id == task_id and not a.superseded:
                a.superseded = True
                retired += 1
        return retired


class _FakeAutoApprovalRepo:
    def __init__(self, store: _Store) -> None:
        self._s = store

    async def get(self, project_id: UUID, user_id: str) -> AutoApproval | None:
        return self._s.auto_approvals.get((project_id, user_id))

    async def set_enabled(
        self, project_id: UUID, user_id: str, *, enabled: bool
    ) -> AutoApproval:
        row = self._s.auto_approvals.get((project_id, user_id)) or AutoApproval(
            project_id=project_id, user_id=user_id
        )
        row.enabled = enabled
        self._s.auto_approvals[(project_id, user_id)] = row
        return row


class _FakeMariusRepo:
    def __init__(self, store: _Store) -> None:
        self._s = store

    async def add(self, marius: Marius) -> Marius:
        self._s.mariuses[marius.id] = marius
        return marius

    async def get(self, marius_id: UUID) -> Marius | None:
        return self._s.mariuses.get(marius_id)

    async def get_by_token(self, token: str) -> Marius | None:
        return next((m for m in self._s.mariuses.values() if m.agent_token == token), None)

    async def list_by_workspace(self, workspace_id: UUID) -> list[Marius]:
        return [m for m in self._s.mariuses.values() if m.workspace_id == workspace_id]

    async def list_by_ids(self, marius_ids: list[UUID]) -> list[Marius]:
        wanted = set(marius_ids)
        return [m for m in self._s.mariuses.values() if m.id in wanted]

    async def update(self, marius: Marius) -> Marius:
        self._s.mariuses[marius.id] = marius
        return marius


class _FakeSkillRepo:
    def __init__(self, store: _Store) -> None:
        self._s = store

    async def add(self, skill: Skill) -> Skill:
        self._s.skills[skill.id] = skill
        return skill

    async def get(self, skill_id: UUID) -> Skill | None:
        return self._s.skills.get(skill_id)

    async def update(self, skill: Skill) -> Skill:
        self._s.skills[skill.id] = skill
        return skill

    async def list_by_workspace(self, workspace_id: UUID) -> list[Skill]:
        return [s for s in self._s.skills.values() if s.workspace_id == workspace_id]

    async def get_by_slug(self, workspace_id: UUID, slug: str) -> Skill | None:
        return next(
            (
                s
                for s in self._s.skills.values()
                if s.workspace_id == workspace_id and s.slug == slug
            ),
            None,
        )

    async def list_by_ids(self, skill_ids: list[UUID]) -> list[Skill]:
        wanted = set(skill_ids)
        return [s for s in self._s.skills.values() if s.id in wanted]


class _FakeOnboardingRepo:
    def __init__(self, store: _Store) -> None:
        self._s = store

    async def add(self, session: OnboardingSession) -> OnboardingSession:
        self._s.onboardings[session.id] = session
        return session

    async def get(self, session_id: UUID) -> OnboardingSession | None:
        return self._s.onboardings.get(session_id)

    async def update(self, session: OnboardingSession) -> OnboardingSession:
        self._s.onboardings[session.id] = session
        return session

    async def list_by_workspace(
        self, workspace_id: UUID
    ) -> list[OnboardingSession]:
        epoch = datetime.min.replace(tzinfo=UTC)
        items = [
            s for s in self._s.onboardings.values() if s.workspace_id == workspace_id
        ]
        items.sort(key=lambda s: s.created_at or epoch, reverse=True)
        return items


class _FakeTaskLogRepo:
    def __init__(self, store: _Store) -> None:
        self._s = store

    async def append(self, entry: TaskLogEntry) -> TaskLogEntry:
        self._s.task_logs[entry.id] = entry
        return entry

    async def next_seq(self, task_id: UUID) -> int:
        seqs = [e.seq for e in self._s.task_logs.values() if e.task_id == task_id]
        return (max(seqs) if seqs else 0) + 1

    async def list_by_task(self, task_id: UUID) -> list[TaskLogEntry]:
        entries = [e for e in self._s.task_logs.values() if e.task_id == task_id]
        entries.sort(key=lambda e: e.seq)
        return entries


class _FakeInboxRepo:
    def __init__(self, store: _Store) -> None:
        self._s = store

    async def add(self, item: InboxItem) -> InboxItem:
        self._s.inbox[item.id] = item
        return item

    async def get(self, item_id: UUID) -> InboxItem | None:
        return self._s.inbox.get(item_id)

    async def update(self, item: InboxItem) -> InboxItem:
        self._s.inbox[item.id] = item
        return item

    async def list_for_recipient(
        self,
        recipient_user_id: str,
        *,
        status: InboxItemStatus | None = None,
        project_id: UUID | None = None,
    ) -> list[InboxItem]:
        epoch = datetime.min.replace(tzinfo=UTC)
        items = [
            i for i in self._s.inbox.values()
            if i.recipient_user_id == recipient_user_id
            and (status is None or i.status == status)
            and (project_id is None or i.project_id == project_id)
        ]
        items.sort(key=lambda i: i.created_at or epoch)
        return items

    async def list_pending(self, *, limit: int = 500) -> list[InboxItem]:
        epoch = datetime.min.replace(tzinfo=UTC)
        items = [i for i in self._s.inbox.values() if i.status == InboxItemStatus.PENDING]
        items.sort(key=lambda i: i.created_at or epoch)
        return items[:limit]

    async def list_pending_for_task(self, task_id: UUID) -> list[InboxItem]:
        epoch = datetime.min.replace(tzinfo=UTC)
        items = [
            i for i in self._s.inbox.values()
            if i.task_id == task_id and i.status == InboxItemStatus.PENDING
        ]
        items.sort(key=lambda i: i.created_at or epoch)
        return items

    async def list_pending_for_project(self, project_id: UUID) -> list[InboxItem]:
        epoch = datetime.min.replace(tzinfo=UTC)
        items = [
            i for i in self._s.inbox.values()
            if i.project_id == project_id and i.status == InboxItemStatus.PENDING
        ]
        items.sort(key=lambda i: i.created_at or epoch)
        return items


class _FakePlacementRepo:
    """Where agents are put to work, in memory.

    Insert-only, exactly like the real one: there is no method here that moves an agent,
    because FR-007 says nothing may, and a fake that allows what production forbids is a
    fake that lets a test pass on behaviour the system does not have.
    """

    def __init__(self, store: _Store) -> None:
        self._s = store

    async def get(self, workspace_id: UUID, placement_id: UUID) -> Placement | None:
        found = self._s.placements.get(placement_id)
        if found is None or found.workspace_id != workspace_id:
            return None
        return found

    async def attach(self, marius_id: UUID, workspace_id: UUID, placement_id: UUID) -> None:
        if marius_id in self._s.attachments:
            raise Conflict("agent_already_placed")
        self._s.attachments[marius_id] = placement_id


def a_placement(store_owner, workspace_id: UUID, *, ready: bool = True,
                not_ready_reason: str | None = None) -> Placement:
    """Put one placement in a fake store and hand it back.

    `store_owner` is a `FakeUowFactory` (or anything with a `.store`). Every agent has to be
    attached to one at creation (FR-007f), so a test that wants an agent needs one of these
    first — which is the point, not an inconvenience: the requirement says there is no such
    thing as an agent that has not been placed.
    """
    placement = Placement(
        id=uuid4(),
        workspace_id=workspace_id,
        ready=ready,
        not_ready_reason=not_ready_reason,
    )
    store_owner.store.placements[placement.id] = placement
    return placement


class FakeUnitOfWork(UnitOfWork):
    """A UoW backed by an in-memory store. Only the repos the Sprint-2 use cases need."""

    def __init__(self, store: _Store) -> None:
        self._store = store

    async def __aenter__(self) -> FakeUnitOfWork:
        s = self._store
        self.workspaces = _FakeWorkspaceRepo(s)  # type: ignore[assignment]
        self.labels = _FakeLabelRepo(s)  # type: ignore[assignment]
        self.onboardings = _FakeOnboardingRepo(s)  # type: ignore[assignment]
        self.projects = _FakeProjectRepo(s)  # type: ignore[assignment]
        self.tasks = _FakeTaskRepo(s)  # type: ignore[assignment]
        self.push_reasons = _FakeTaskPushReasonRepo(s)  # type: ignore[assignment]
        self.runs = _FakeRunRepo(s)  # type: ignore[assignment]
        self.criteria = _FakeChecklistItemRepo(s)  # type: ignore[assignment]
        self.task_logs = _FakeTaskLogRepo(s)  # type: ignore[assignment]
        self.inbox = _FakeInboxRepo(s)  # type: ignore[assignment]
        self.dependencies = _FakeTaskDependencyRepo(s)  # type: ignore[assignment]
        self.roles = _FakeRoleRepo(s)  # type: ignore[assignment]
        self.seat_grants = _FakeSeatGrantRepo(s)  # type: ignore[assignment]
        self.approvals = _FakeApprovalRepo(s)  # type: ignore[assignment]
        self.auto_approvals = _FakeAutoApprovalRepo(s)  # type: ignore[assignment]
        self.mariuses = _FakeMariusRepo(s)  # type: ignore[assignment]
        self.placements = _FakePlacementRepo(s)  # type: ignore[assignment]
        self.skills = _FakeSkillRepo(s)  # type: ignore[assignment]
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        return None

    async def commit(self) -> None:
        return None  # repos already wrote through to the shared store

    async def rollback(self) -> None:
        return None


class FakeUowFactory:
    """Callable that hands out `FakeUnitOfWork`s over one shared store (introspect `.store`)."""

    def __init__(self) -> None:
        self.store = _Store()

    def __call__(self) -> FakeUnitOfWork:
        return FakeUnitOfWork(self.store)


class FakeLivenessProbe(LivenessProbe):
    """Scripted probe: a constant answer, or a list consumed one per call (default miss)."""

    def __init__(self, answers: bool | list[bool] = False) -> None:
        self._answers = answers
        self.calls = 0

    async def probe(self, marius: Marius) -> bool:
        self.calls += 1
        if isinstance(self._answers, bool):
            return self._answers
        idx = min(self.calls - 1, len(self._answers) - 1)
        return self._answers[idx]


_ONBOARDING_PREFIX = "armarius:onboarding:"


def _onboarding_id(ctx):
    """The onboarding session id the service embeds in ctx.session_params, parsed to a UUID
    (the service's agent-callback methods key on UUID, not the raw string)."""
    from uuid import UUID

    raw = (ctx.session_params or {}).get("session_id") or ""
    if not raw.startswith(_ONBOARDING_PREFIX):
        return None
    try:
        return UUID(raw[len(_ONBOARDING_PREFIX):])
    except ValueError:
        return None


class FakeAdapter(MariusAdapter):
    """Stands in for a real runtime when driving onboarding in tests.

    Each ``execute`` runs one scripted WA callback queued in ``drivers`` (an async
    ``(session_id) -> None``), then returns the scripted ``status`` — or raises, to simulate an
    unreachable runtime. A driver typically calls the onboarding service's agent callbacks
    (``agent_post_question`` / ``agent_post_complete``) to mimic a live Workspace Agent.
    """

    type = "fake"
    capabilities = AdapterCapabilities(resumable=True, streaming=False, transport="fake")

    def __init__(
        self,
        *,
        status: RunStatus = RunStatus.COMPLETED,
        drivers: list | None = None,
        raise_on_execute: BaseException | None = None,
    ) -> None:
        self.status = status
        self.drivers: list = list(drivers or [])
        self.raise_on_execute = raise_on_execute
        self.executes = 0

    async def execute(self, ctx) -> ExecResult:
        self.executes += 1
        if self.raise_on_execute is not None:
            raise self.raise_on_execute
        if self.drivers:
            driver = self.drivers.pop(0)
            sid = _onboarding_id(ctx)
            if sid is not None:
                await driver(sid)
        return ExecResult(status=self.status, session_params=dict(ctx.session_params))

    async def test_environment(self, config: dict) -> Diagnostics:
        return Diagnostics(ok=True, detail="fake")

