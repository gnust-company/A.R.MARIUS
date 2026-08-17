"""Project & roster use cases (LLD §3.1, §4) — the roster-driven project lifecycle.

Three responsibilities the application layer owns on top of the pure rules in
`domain.services.project_rules`:
  - **create with the hard rule** — a project is born with a roster that has exactly one
    leader seat and at least one worker role (`validate_plan`); it starts in SETUP.
  - **system-only seat grants** — only the system assigns a Marius to a seat; every grant
    re-evaluates activation.
  - **activation** — `recompute_active` flips SETUP→PLANNING once every seat is granted
    and every seated agent is ONLINE; it never rolls back. A full roster buys the right to
    *plan*, not to start work (spec 001 FR-002).
  - **phase changes** — the Leader proposes, the patron decides (FR-004); a closed project
    refuses every write (FR-005).
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass, field, fields
from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID

from armarius.application.ports.unit_of_work import UnitOfWork
from armarius.application.use_cases.types import UowFactory
from armarius.domain.entities.project import Project, ProjectStatus, ProjectThresholds
from armarius.domain.entities.role import Role
from armarius.domain.entities.seat_grant import SeatGrant, SeatGrantStatus
from armarius.domain.services import project_key, project_rules
from armarius.domain.services.project_rules import ProjectClosed
from armarius.shared.clock import utcnow
from armarius.shared.logging import get_logger

if TYPE_CHECKING:  # imported for typing only — these are injected, never constructed here
    from armarius.application.use_cases.inbox import InboxService
    from armarius.application.use_cases.leader_chat import LeaderChatService
    from armarius.infrastructure.events.topic_bus import TopicEventBus

logger = get_logger(__name__)


class SystemOnlyOperation(Exception):
    """Raised when a seat grant/revoke is attempted by a non-system actor (LLD §3.3)."""


class DuplicateRoleKey(Exception):
    """Raised when a role would collide with an existing roster key (API_CONTRACT §3.3)."""


class DuplicateProjectKey(Exception):
    """Raised when a project key collides with an existing one in the same workspace."""


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug or "untitled"


@dataclass(frozen=True)
class RoleSpec:
    """A roster seat at create/edit time (becomes a `Role`)."""

    key: str
    title: str
    seats: int = 1
    is_leader: bool = False
    description: str = ""
    skill_ids: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class SeatView:
    """A granted agent in a role, with its current liveness (API_CONTRACT §3.3)."""

    marius_id: UUID
    name: str
    role_key: str
    liveness: str
    is_primary: bool


@dataclass(frozen=True)
class RosterRoleView:
    """A roster role with its seat fill and seated agents (API_CONTRACT §3.3)."""

    key: str
    title: str
    seats: int
    is_leader: bool
    description: str
    skill_ids: list[str]
    filled: int
    seated: list[SeatView]


class ProjectService:
    def __init__(
        self,
        uow_factory: UowFactory,
        system_thresholds: ProjectThresholds | None = None,
        *,
        control_bus: TopicEventBus | None = None,
        inbox: InboxService | None = None,
        leader_chat: LeaderChatService | None = None,
    ) -> None:
        self._uow = uow_factory
        # Phase changes need to reach the board, the patron's inbox and the Leader. All
        # optional so narrow unit tests can build the service with a UoW alone.
        self._bus = control_bus
        self._inbox = inbox
        self._leader_chat = leader_chat
        # The system floor every project falls back to (spec 001). Injected so the domain
        # and application layers never read the environment; None only in narrow tests
        # that do not touch thresholds.
        self._system_thresholds = system_thresholds

    # ── create with the hard roster rule ────────────────────────────────────────
    async def create_project(
        self,
        workspace_id: UUID,
        name: str,
        *,
        roles: Sequence[RoleSpec],
        key: str | None = None,
        description: str | None = None,
        objective: str | None = None,
        success_metrics: dict | None = None,
        target_date: datetime | None = None,
        context: str | None = None,
        created_by_user_id: str | None = None,
    ) -> Project:
        """Create a SETUP project with its roster. Raises InvalidProjectPlan if the
        roster violates the leader/worker rule; InvalidProjectKey if `key` is malformed;
        DuplicateProjectKey if `key` is taken in this workspace; LookupError if the
        workspace is gone. A missing `key` is suggested from `name` and auto-uniquified."""
        draft_roles = [self._role_from_spec(spec) for spec in roles]
        project_rules.validate_plan(draft_roles)  # hard rule — raises InvalidProjectPlan

        now = utcnow()
        async with self._uow() as uow:
            if await uow.workspaces.get(workspace_id) is None:
                raise LookupError("workspace not found")
            # Resolve the JIRA-style KEY: explicit → validate + reject-on-collision;
            # missing → suggest from name and auto-uniquify (suffix a digit).
            if key and key.strip():
                resolved_key = project_key.validate_project_key(key)  # raises InvalidProjectKey
                if await uow.projects.get_by_key(workspace_id, resolved_key) is not None:
                    raise DuplicateProjectKey(
                        f"project key '{resolved_key}' is already used in this workspace"
                    )
            else:
                base = project_key.suggest_project_key(name)
                resolved_key, suffix = base, 2
                while await uow.projects.get_by_key(workspace_id, resolved_key) is not None:
                    resolved_key = f"{base}{suffix}"
                    suffix += 1
            project = Project(
                workspace_id=workspace_id,
                name=name,
                slug=_slugify(name),
                key=resolved_key,
                description=description,
                objective=objective,
                success_metrics=success_metrics,
                target_date=target_date,
                context=context,
                status=ProjectStatus.SETUP,
                created_by_user_id=created_by_user_id,
                created_at=now,
                updated_at=now,
            )
            await uow.projects.add(project)
            for role in draft_roles:
                role.project_id = project.id
                role.created_at = now
                await uow.roles.add(role)
            await uow.commit()
            return project

    @staticmethod
    def _role_from_spec(spec: RoleSpec) -> Role:
        return Role(
            key=spec.key,
            title=spec.title,
            seats=spec.seats,
            is_leader=spec.is_leader,
            description=spec.description,
            skill_ids=list(spec.skill_ids),
        )

    # ── roster CRUD ─────────────────────────────────────────────────────────────
    async def list_roles(self, project_id: UUID) -> Sequence[Role]:
        async with self._uow() as uow:
            return await uow.roles.list_by_project(project_id)

    async def add_role(self, project_id: UUID, spec: RoleSpec) -> Role:
        # add_role bypasses validate_plan (it adds one role to an existing roster), so it
        # enforces the same "every role has a description" rule itself (spec 03 §3.1, #112).
        if not (spec.description or "").strip():
            raise project_rules.InvalidProjectPlan(
                f"role '{spec.title or spec.key}' needs a description of what it does."
            )
        async with self._uow() as uow:
            if await uow.projects.get(project_id) is None:
                raise LookupError("project not found")
            existing = await uow.roles.list_by_project(project_id)
            if any(r.key == spec.key for r in existing):
                raise DuplicateRoleKey(
                    f"role key '{spec.key}' already exists in this project's roster"
                )
            role = self._role_from_spec(spec)
            role.project_id = project_id
            role.created_at = utcnow()
            created = await uow.roles.add(role)
            await uow.commit()
            return created

    @staticmethod
    def _mutate_role(
        role: Role,
        *,
        title: str | None = None,
        seats: int | None = None,
        description: str | None = None,
        skill_ids: list[str] | None = None,
    ) -> None:
        if title is not None:
            role.title = title
        if seats is not None:
            role.seats = seats
        if description is not None:
            # Sửa role không được xoá trắng mô tả (spec 03 §3.1, #112). Chuỗi rỗng đã bị
            # schema chặn; ở đây bắt luôn trường hợp toàn-khoảng-trắng, đồng bộ add_role.
            if not description.strip():
                raise project_rules.InvalidProjectPlan(
                    "A role's description cannot be blanked out."
                )
            role.description = description
        if skill_ids is not None:
            role.skill_ids = skill_ids

    async def update_role(self, role_id: UUID, **changes) -> Role:
        async with self._uow() as uow:
            role = await uow.roles.get(role_id)
            if role is None:
                raise LookupError("role not found")
            self._mutate_role(role, **changes)
            updated = await uow.roles.update(role)
            await uow.commit()
            return updated

    async def remove_role(self, role_id: UUID) -> None:
        async with self._uow() as uow:
            await uow.roles.remove(role_id)
            await uow.commit()

    # ── project detail / brief / delete ──────────────────────────────────────────
    async def get_project(self, project_id: UUID) -> Project | None:
        async with self._uow() as uow:
            return await uow.projects.get(project_id)

    async def update_project(
        self,
        project_id: UUID,
        *,
        description: str | None = None,
        objective: str | None = None,
        success_metrics: dict | None = None,
        target_date=None,
        github_url: str | None = None,
        context: str | None = None,
        settings: dict | None = None,
    ) -> Project:
        """Edit project brief fields (API_CONTRACT §3). Only non-None fields change."""
        async with self._uow() as uow:
            project = await uow.projects.get(project_id)
            if project is None:
                raise LookupError("project not found")
            if description is not None:
                project.description = description
            if objective is not None:
                project.objective = objective
            if success_metrics is not None:
                project.success_metrics = success_metrics
            if target_date is not None:
                project.target_date = target_date
            if github_url is not None:
                project.github_url = github_url
            if context is not None:
                project.context = context
            if settings is not None:
                project.settings = settings
            project.updated_at = utcnow()
            updated = await uow.projects.update(project)
            await uow.commit()
            return updated

    # ── timing thresholds (spec 001) ──────────────────────────────────────────────
    async def get_thresholds(self, project_id: UUID) -> ProjectThresholds:
        """The project's effective thresholds — system floor plus its own overrides."""
        async with self._uow() as uow:
            project = await uow.projects.get(project_id)
            if project is None:
                raise LookupError("project not found")
        return self._resolve(project)

    async def set_thresholds(
        self, project_id: UUID, overrides: dict[str, object]
    ) -> ProjectThresholds:
        """Store per-project overrides. Only keys that name a real threshold survive, and
        an empty dict resets the project back to the system floor."""
        async with self._uow() as uow:
            project = await uow.projects.get(project_id)
            if project is None:
                raise LookupError("project not found")
            known = {f.name for f in fields(ProjectThresholds)}
            project.settings = {
                **project.settings,
                "thresholds": {k: v for k, v in overrides.items() if k in known},
            }
            project.updated_at = utcnow()
            updated = await uow.projects.update(project)
            await uow.commit()
        return self._resolve(updated)

    def _resolve(self, project: Project) -> ProjectThresholds:
        if self._system_thresholds is None:
            raise RuntimeError("ProjectService was built without system thresholds")
        return self._system_thresholds.with_overrides(
            (project.settings or {}).get("thresholds")
        )

    async def delete_project(self, project_id: UUID) -> None:
        async with self._uow() as uow:
            if await uow.projects.get(project_id) is None:
                raise LookupError("project not found")
            await uow.projects.remove(project_id)
            await uow.commit()

    # ── roster / participant views ────────────────────────────────────────────────
    async def get_roster(self, project_id: UUID) -> list[RosterRoleView]:
        """Roles with seat fill + seated agents and their liveness (API_CONTRACT §3.3)."""
        async with self._uow() as uow:
            if await uow.projects.get(project_id) is None:
                raise LookupError("project not found")
            roles = await uow.roles.list_by_project(project_id)
            grants = await uow.seat_grants.list_by_project(project_id)
            # Batch-load every seated agent once (avoids an N+1 over the grants).
            seated_ids = {
                g.marius_id
                for g in grants
                if g.status == SeatGrantStatus.GRANTED and g.marius_id is not None
            }
            mariuses = {
                m.id: m for m in await uow.mariuses.list_by_ids(list(seated_ids))
            }
            views: list[RosterRoleView] = []
            for role in roles:
                seated: list[SeatView] = []
                for g in grants:
                    if g.status != SeatGrantStatus.GRANTED or g.role_key != role.key:
                        continue
                    if g.marius_id is None:
                        continue
                    marius = mariuses.get(g.marius_id)
                    if marius is None:
                        continue
                    seated.append(
                        SeatView(
                            marius_id=marius.id,
                            name=marius.name,
                            role_key=role.key,
                            liveness=str(marius.liveness),
                            is_primary=role.is_leader,
                        )
                    )
                views.append(
                    RosterRoleView(
                        key=role.key,
                        title=role.title,
                        seats=role.seats,
                        is_leader=role.is_leader,
                        description=role.description,
                        skill_ids=[str(x) for x in role.skill_ids],
                        filled=len(seated),
                        seated=seated,
                    )
                )
            return views

    async def list_agents(self, project_id: UUID) -> list[SeatView]:
        """Flat list of project participants (granted seats) — API_CONTRACT §4."""
        roster = await self.get_roster(project_id)
        return [seat for role in roster for seat in role.seated]

    async def list_with_seat_counts(
        self, workspace_id: UUID
    ) -> list[tuple[Project, int, int]]:
        """Workspace projects, each with (seats_total, seats_filled) for the list view.

        The project *card* shows the roster fill without opening the detail view, so the
        list must carry counts (the entity has none). One UoW, roles+grants per project —
        the project list is small, so the per-project reads are acceptable here.
        """
        async with self._uow() as uow:
            projects = await uow.projects.list_by_workspace(workspace_id)
            rows: list[tuple[Project, int, int]] = []
            for project in projects:
                roles = await uow.roles.list_by_project(project.id)
                grants = await uow.seat_grants.list_by_project(project.id)
                seats_total = sum(r.seats for r in roles)
                seats_filled = sum(
                    1
                    for g in grants
                    if g.status == SeatGrantStatus.GRANTED and g.marius_id is not None
                )
                rows.append((project, seats_total, seats_filled))
            return rows

    # ── roster CRUD by role_key (the contract addresses roles by key) ─────────────
    async def _role_by_key(self, uow, project_id: UUID, role_key: str) -> Role:
        roles = await uow.roles.list_by_project(project_id)
        role = next((r for r in roles if r.key == role_key), None)
        if role is None:
            raise LookupError(f"role '{role_key}' not in project roster")
        return role

    async def update_role_by_key(
        self, project_id: UUID, role_key: str, **changes
    ) -> Role:
        # Resolve-by-key and mutate in a single transaction (one round-trip, no read→write
        # race window between two separate UoWs).
        async with self._uow() as uow:
            role = await self._role_by_key(uow, project_id, role_key)
            self._mutate_role(role, **changes)
            updated = await uow.roles.update(role)
            await uow.commit()
            return updated

    async def remove_role_by_key(self, project_id: UUID, role_key: str) -> None:
        """Remove a role — only if no agent currently holds a seat in it (§3.3)."""
        async with self._uow() as uow:
            role = await self._role_by_key(uow, project_id, role_key)
            grants = await uow.seat_grants.list_by_project(project_id)
            if any(
                g.status == SeatGrantStatus.GRANTED and g.role_key == role_key
                for g in grants
            ):
                raise ValueError("Cannot remove a role while an agent holds its seat.")
            await uow.roles.remove(role.id)
            await uow.commit()

    # ── system-only seat grants ─────────────────────────────────────────────────
    async def grant_seat(
        self,
        project_id: UUID,
        role_key: str,
        marius_id: UUID,
        *,
        system: bool = False,
        granted_by_user_id: str | None = None,
    ) -> SeatGrant:
        """Seat a Marius. SYSTEM-ONLY: a non-system caller is rejected (LLD §3.3).

        Re-evaluates activation after the grant. Returns the new grant.

        ``granted_by_user_id`` records **which patron** put this agent here (FR-034) —
        the one who will have to sign for its output. Captured at the moment of the grant
        because it cannot be reconstructed afterwards: today it happens to equal the
        workspace owner, and a later guess would be indistinguishable from a fact.
        """
        if not system:
            raise SystemOnlyOperation("Seat grants are issued by the system only.")
        now = utcnow()
        async with self._uow() as uow:
            project = await uow.projects.get(project_id)
            if project is None:
                raise LookupError("project not found")
            roles = await uow.roles.list_by_project(project_id)
            if not any(r.key == role_key for r in roles):
                raise LookupError(f"role '{role_key}' not in project roster")
            if await uow.mariuses.get(marius_id) is None:
                raise LookupError("marius not found")
            grant = SeatGrant(
                project_id=project_id,
                role_key=role_key,
                marius_id=marius_id,
                status=SeatGrantStatus.GRANTED,
                granted_by_user_id=granted_by_user_id,
                granted_at=now,
                created_at=now,
            )
            await uow.seat_grants.add(grant)
            flipped = await self._recompute_active(uow, project)
            await uow.commit()

        if flipped:
            await self._announce_planning(project_id)
        return grant

    async def list_seat_grants(self, project_id: UUID) -> Sequence[SeatGrant]:
        async with self._uow() as uow:
            return await uow.seat_grants.list_by_project(project_id)

    async def revoke_seat(self, grant_id: UUID, *, system: bool = False) -> SeatGrant:
        """Revoke a seat. SYSTEM-ONLY. Activation never rolls back (LLD §4)."""
        if not system:
            raise SystemOnlyOperation("Seat revokes are issued by the system only.")
        async with self._uow() as uow:
            grant = await uow.seat_grants.get(grant_id)
            if grant is None:
                raise LookupError("seat grant not found")
            grant.revoke()  # raises SeatGrantError if already revoked
            updated = await uow.seat_grants.update(grant)
            await uow.commit()
            return updated

    async def revoke_seat_by_role(
        self,
        project_id: UUID,
        marius_id: UUID,
        role_key: str,
        *,
        system: bool = False,
    ) -> SeatGrant:
        """Revoke the GRANTED seat for (marius, role) in a project. SYSTEM-ONLY (§3.3)."""
        if not system:
            raise SystemOnlyOperation("Seat revokes are issued by the system only.")
        async with self._uow() as uow:
            grants = await uow.seat_grants.list_by_project(project_id)
            grant = next(
                (
                    g
                    for g in grants
                    if g.marius_id == marius_id
                    and g.role_key == role_key
                    and g.status == SeatGrantStatus.GRANTED
                ),
                None,
            )
            if grant is None:
                raise LookupError("no granted seat for that agent/role")
            grant.revoke()
            updated = await uow.seat_grants.update(grant)
            await uow.commit()
            return updated

    # ── activation ──────────────────────────────────────────────────────────────
    async def recompute_active(self, project_id: UUID) -> bool:
        """Re-evaluate the activation predicate; flip SETUP→ACTIVE once. Returns True
        iff it just activated."""
        async with self._uow() as uow:
            project = await uow.projects.get(project_id)
            if project is None:
                raise LookupError("project not found")
            flipped = await self._recompute_active(uow, project)
            if flipped:
                await uow.commit()

        if flipped:
            await self._announce_planning(project_id)
        return flipped

    # ── phase changes (spec 001 FR-004, FR-005) ─────────────────────────────────
    async def propose_phase(
        self, project_id: UUID, *, target_phase: ProjectStatus, reason: str
    ) -> None:
        """The Leader asks for a phase change; it parks in the patron's inbox.

        Deliberately changes nothing by itself — an agent never moves a project between
        phases (FR-004). The proposal is a question, and the patron answers it by calling
        `change_phase`.
        """
        async with self._uow() as uow:
            project = await self._writable(uow, project_id)
            project_rules.assert_phase_transition(project.status, target_phase)
            workspace_id = project.workspace_id
            recipient = project.created_by_user_id

        if self._inbox is None or not recipient or workspace_id is None:
            return
        from armarius.domain.entities.inbox_item import InboxItemKind

        await self._inbox.place(
            workspace_id=workspace_id,
            recipient_user_id=recipient,
            kind=InboxItemKind.PHASE_DECISION,
            title=f"Trưởng dự án đề xuất chuyển sang giai đoạn '{target_phase}'",
            body=reason,
            project_id=project_id,
        )

    # Ba lựa chọn người chủ có sau khi một đợt việc khép lại (FR-043). Vocabulary trên
    # dây — giao diện hiển thị nhãn, tầng này không dịch.
    SPRINT_CHOICES: tuple[str, ...] = ("dong_du_an", "chuyen_bao_tri", "mo_dot_moi")

    async def has_open_tasks(self, project_id: UUID) -> bool:
        """Còn đầu việc nào chưa khép trong dự án không?"""
        async with self._uow() as uow:
            tasks = await uow.tasks.list_by_project(project_id)
        return any(str(t.status) not in {"done", "cancelled"} for t in tasks)

    async def submit_sprint_summary(self, project_id: UUID, *, summary: str) -> None:
        """The Leader's wrap-up for a finished batch, parked on the patron (FR-043).

        There is **no project-level acceptance gate** (FR-042): the work was already
        accepted task by task. What the patron gets here is a decision about what happens
        next — close, move to maintenance, or open another batch — not a second review of
        work already signed off.
        """
        async with self._uow() as uow:
            project = await self._writable(uow, project_id)
            workspace_id = project.workspace_id
            recipient = project.created_by_user_id

        if self._inbox is None or not recipient or workspace_id is None:
            return
        from armarius.domain.entities.inbox_item import InboxItemKind

        await self._inbox.place(
            workspace_id=workspace_id,
            recipient_user_id=recipient,
            kind=InboxItemKind.PHASE_DECISION,
            title=f"Đợt việc đã khép — {project.name}",
            body=summary,
            project_id=project_id,
            attempt_dossier={"choices": list(self.SPRINT_CHOICES)},
        )

    async def change_phase(
        self,
        project_id: UUID,
        *,
        user_id: str,
        target_phase: ProjectStatus,
        reason: str | None = None,
    ) -> Project:
        """The patron moves the project. The only way a phase ever changes (FR-004).

        Closing is terminal and takes the wake cadence with it: once closed, nothing wakes
        for this project again, so the team simply runs out of work — there is nothing to
        announce to them (FR-005).

        It takes the project's open letters with it too. A question about a closed project
        can never be answered — every action it offers is refused from here on — so leaving
        it in the patron's waiting list would leave a count that never comes down and a
        reminder ladder chasing an answer nobody is allowed to give.
        """
        async with self._uow() as uow:
            project = await self._writable(uow, project_id)
            before = project.status
            project_rules.assert_phase_transition(before, target_phase)
            # Leaving *planning* is the plan gate's decision, not a free phase move: the
            # patron approves a plan and the project follows. Without this, this route
            # would be a way to skip the approval FR-011 exists to require.
            if before is ProjectStatus.PLANNING:
                raise project_rules.InvalidPhaseTransition(
                    "Rời giai đoạn lập kế hoạch bằng cách duyệt kế hoạch, "
                    "không đổi giai đoạn thẳng."
                )
            project.status = target_phase
            project.updated_at = utcnow()
            updated = await uow.projects.update(project)
            await uow.commit()

        await self._publish(
            project_id,
            "project.phase_changed",
            {
                "before": str(before),
                "after": str(target_phase),
                "decided_by": user_id,
                "reason": reason,
            },
        )
        if project_rules.is_closed(target_phase):
            await self._retire_open_letters(project_id)
        else:
            await self._resolve_phase_questions(project_id, updated.created_by_user_id)
        return updated

    async def _announce_planning(self, project_id: UUID) -> None:
        """The roster just filled and everyone is online — wake the Leader once (FR-002).

        Once, on the flip only: `recompute_active` is one-way, so this cannot fire twice
        for the same project no matter how many grants or liveness signals arrive later.
        """
        await self._publish(
            project_id,
            "project.phase_changed",
            {
                "before": str(ProjectStatus.SETUP),
                "after": str(ProjectStatus.PLANNING),
                "decided_by": "system",
                "reason": "đủ đội và mọi thợ đã trực tuyến",
            },
        )
        if self._leader_chat is None:
            return
        from armarius.domain.entities.run import WakeSource
        from armarius.domain.services.wake_reason import reason as wake_reason

        try:
            await self._leader_chat.notify(
                project_id=project_id,
                source=WakeSource.PROJECT_READY,
                reason=wake_reason("roster_complete"),
                detail=(
                    "Settle the project brief with the patron first, then draft the plan "
                    "and submit it for their approval."
                ),
            )
        except LookupError:  # pragma: no cover - project vanished mid-flight
            return

    async def _writable(self, uow: UnitOfWork, project_id: UUID) -> Project:
        """Load a project and refuse every write once it is closed (FR-005)."""
        project = await uow.projects.get(project_id)
        if project is None:
            raise LookupError("project not found")
        if project_rules.is_closed(project.status):
            raise ProjectClosed("This project is closed — its history is read-only.")
        return project

    async def assert_writable(self, project_id: UUID) -> Project:
        """Public form of the closed-project guard, for callers outside this service."""
        async with self._uow() as uow:
            return await self._writable(uow, project_id)

    async def _retire_open_letters(self, project_id: UUID) -> None:
        """Closing the project retires every letter it left open, of every kind.

        The wider cousin of `_resolve_phase_questions`, and for the same reason: the patron
        does not tidy up by hand. Wider because closing does not answer one question, it
        ends all of them — the phase decision, the escalations, the outputs waiting to be
        judged, the Leader's questions.
        """
        if self._inbox is None:
            return
        retired = await self._inbox.void_for_project(project_id)
        if retired:
            logger.info("project %s closed; retired %s open letters", project_id, retired)

    async def _resolve_phase_questions(
        self, project_id: UUID, recipient: str | None
    ) -> None:
        """Deciding closes what was waiting — the patron does not tidy up by hand."""
        if self._inbox is None or not recipient:
            return
        from armarius.domain.entities.inbox_item import InboxItemKind

        for item in await self._inbox.list_for(recipient, project_id=project_id):
            if item.kind is InboxItemKind.PHASE_DECISION:
                await self._inbox.resolve(item.id)

    async def _publish(
        self, project_id: UUID, event: str, payload: dict[str, object]
    ) -> None:
        if self._bus is None:
            return
        from armarius.infrastructure.events.topic_bus import project_topic

        await self._bus.publish(project_topic(project_id), event, payload)

    @staticmethod
    async def _recompute_active(uow: UnitOfWork, project: Project) -> bool:
        roles = await uow.roles.list_by_project(project.id)
        grants = await uow.seat_grants.list_by_project(project.id)
        liveness_by_marius = {}
        for g in grants:
            if g.status != SeatGrantStatus.GRANTED or g.marius_id is None:
                continue
            marius = await uow.mariuses.get(g.marius_id)
            if marius is not None:
                liveness_by_marius[g.marius_id] = marius.liveness
        flipped = project_rules.recompute_active(
            project, roles, grants, liveness_by_marius
        )
        if flipped:
            project.updated_at = utcnow()
            await uow.projects.update(project)
        return flipped
