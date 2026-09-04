"""Project & roster use cases (LLD §3.1, §4) — the roster-driven project lifecycle.

Three responsibilities the application layer owns on top of the pure rules in
`domain.services.project_rules`:
  - **create with the hard rule** — a project is born with the roster the *system* fixes:
    the leader seat, and the bench everybody else sits on (`validate_plan`); it starts in
    SETUP. Nobody outside supplies that roster, which is the whole of FR-007l: putting an
    agent on a project is putting the agent there, not inventing a role for it to be.
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
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass, fields
from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID

from armarius.application.ports.unit_of_work import UnitOfWork
from armarius.application.use_cases.seats import leader_role_ids
from armarius.application.use_cases.types import UowFactory
from armarius.domain.entities.project import Project, ProjectStatus, ProjectThresholds
from armarius.domain.entities.role import Role
from armarius.domain.entities.seat_grant import SeatGrant
from armarius.domain.services import project_key, project_rules
from armarius.domain.services.project_rules import ProjectClosed
from armarius.shared.clock import utcnow
from armarius.shared.errors import BadRequest, CodedError, NotFound
from armarius.shared.logging import get_logger

if TYPE_CHECKING:  # imported for typing only — these are injected, never constructed here
    from armarius.application.use_cases.inbox import InboxService
    from armarius.application.use_cases.leader_chat import LeaderChatService
    from armarius.infrastructure.events.topic_bus import TopicEventBus

logger = get_logger(__name__)


class SystemOnlyOperation(CodedError):
    """Raised when a seat grant/revoke is attempted by a non-system actor (LLD §3.3)."""


class DuplicateProjectKey(CodedError):
    """Raised when a project key collides with an existing one in the same workspace."""


# The two rows every project's roster is made of, and the only two an agent can be put on.
#
# Neither is designed by anyone. The leader row is the project's coordinating position, which
# survives on purpose (Constitution V). The bench is where every other agent sits, and it
# describes nobody: what an agent does comes from the instructions written on the agent
# itself, and a role saying it a second time is a second copy that drifts from the first
# (FR-007l). So there is no door here that makes a role, and no caller that names one.
LEADER_ROLE_KEY = "leader"
LEADER_ROLE_TITLE = "Project Leader"
MEMBERS_ROLE_KEY = "members"
# Lower-case because of where it is read: the packet a member is woken with says "you are
# NAME, the team member on this project".
MEMBERS_ROLE_TITLE = "team member"
# English, and written to be read by an agent — it reaches that same packet (Constitution
# VII). It says where behaviour comes from rather than describing any, because the row it
# belongs to is not a description of anybody.
MEMBERS_ROLE_DESCRIPTION = (
    "A member of this project's team. What this agent does, and how it works, is written in "
    "its own instructions rather than here."
)


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug or "untitled"


def _places(role: Role, seated: int) -> int:
    """How many places a roster row has: what it asked for, or who is on it — the larger.

    The bench asks for one and holds however many are on it, so the stored number alone
    would tell the patron a project of four agents had two seats. Written as one rule over
    both rows rather than a special case for the bench: for a row that really was promised
    to a fixed number of agents, nobody can be seated past it, so the two agree anyway.
    """
    return max(role.seats, seated)


@dataclass(frozen=True)
class SeatGrantView:
    """One seat on the way out.

    The seat itself points at the role by identity; the contract addresses roles by key, so
    the key is resolved here, once, rather than by each caller joining the two tables again.
    """

    id: UUID
    project_id: UUID
    role_key: str
    marius_id: UUID
    granted_by_user_id: str | None = None
    granted_at: datetime | None = None
    created_at: datetime | None = None


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
        leader_description: str,
        key: str | None = None,
        description: str | None = None,
        objective: str | None = None,
        success_metrics: dict | None = None,
        target_date: datetime | None = None,
        context: str | None = None,
        created_by_user_id: str | None = None,
    ) -> Project:
        """Create a SETUP project with its roster. Raises InvalidProjectPlan if the leader
        has no description; InvalidProjectKey if `key` is malformed; DuplicateProjectKey if
        `key` is taken in this workspace; NotFound if the workspace is gone. A missing `key`
        is suggested from `name` and auto-uniquified.

        **The roster is not a parameter of this call and must not become one.** It is the
        same two rows for every project — the leader seat and the bench — and the only thing
        the caller says about them is what this project's Leader is there to do. A caller
        that could hand in roles is the flow FR-007l closes: it made the patron design a
        second description of behaviour beside the one already written on each agent.
        """
        draft_roles = [
            Role(
                key=LEADER_ROLE_KEY,
                title=LEADER_ROLE_TITLE,
                seats=1,
                is_leader=True,
                description=(leader_description or "").strip(),
            ),
            Role(
                key=MEMBERS_ROLE_KEY,
                title=MEMBERS_ROLE_TITLE,
                seats=1,
                description=MEMBERS_ROLE_DESCRIPTION,
            ),
        ]
        # Still checked, and deliberately: the rule is what says a project has one leader
        # and somewhere for workers to be, and it is the one thing standing between a blank
        # leader brief and a Leader woken with nothing to say it is the Leader.
        project_rules.validate_plan(draft_roles)  # hard rule — raises InvalidProjectPlan

        now = utcnow()
        async with self._uow() as uow:
            if await uow.workspaces.get(workspace_id) is None:
                raise NotFound("workspace_not_found")
            # Resolve the JIRA-style KEY: explicit → validate + reject-on-collision;
            # missing → suggest from name and auto-uniquify (suffix a digit).
            if key and key.strip():
                resolved_key = project_key.validate_project_key(key)  # raises InvalidProjectKey
                if await uow.projects.get_by_key(workspace_id, resolved_key) is not None:
                    raise DuplicateProjectKey("project_key_taken", key=resolved_key)
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

    # ── roster reads ────────────────────────────────────────────────────────────
    async def list_roles(self, project_id: UUID) -> Sequence[Role]:
        async with self._uow() as uow:
            return await uow.roles.list_by_project(project_id)

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
                raise NotFound("project_not_found")
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
                raise NotFound("project_not_found")
        return self._resolve(project)

    async def set_thresholds(
        self, project_id: UUID, overrides: dict[str, object]
    ) -> ProjectThresholds:
        """Store per-project overrides. Only keys that name a real threshold survive, and
        an empty dict resets the project back to the system floor."""
        async with self._uow() as uow:
            project = await uow.projects.get(project_id)
            if project is None:
                raise NotFound("project_not_found")
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
                raise NotFound("project_not_found")
            await uow.projects.remove(project_id)
            await uow.commit()

    # ── roster / participant views ────────────────────────────────────────────────
    async def get_roster(self, project_id: UUID) -> list[RosterRoleView]:
        """Roles with seat fill + seated agents and their liveness (API_CONTRACT §3.3)."""
        async with self._uow() as uow:
            if await uow.projects.get(project_id) is None:
                raise NotFound("project_not_found")
            roles = await uow.roles.list_by_project(project_id)
            grants = await uow.seat_grants.list_by_project(project_id)
            # Batch-load every seated agent once (avoids an N+1 over the grants).
            seated_ids = {g.marius_id for g in grants}
            mariuses = {
                m.id: m for m in await uow.mariuses.list_by_ids(list(seated_ids))
            }
            views: list[RosterRoleView] = []
            for role in roles:
                seated: list[SeatView] = []
                for g in grants:
                    if g.role_id != role.id:
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
                        seats=_places(role, len(seated)),
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
                per_role = Counter(g.role_id for g in grants)
                seats_total = sum(_places(r, per_role.get(r.id, 0)) for r in roles)
                seats_filled = len(grants)
                rows.append((project, seats_total, seats_filled))
            return rows

    # ── the two rows an agent can be put on ───────────────────────────────────────
    async def _role_by_key(self, uow, project_id: UUID, role_key: str) -> Role:
        roles = await uow.roles.list_by_project(project_id)
        role = next((r for r in roles if r.key == role_key), None)
        if role is None:
            raise NotFound("role_not_in_roster", role=role_key)
        return role

    async def _bench(
        self,
        uow,  # noqa: ANN001
        project_id: UUID,
        roles: Sequence[Role],
    ) -> Role:
        """The row this project's members sit on, made now if the project has none.

        Made rather than demanded, because a project created before the bench existed has a
        roster somebody typed — worker roles with real titles — and this door may not rewrite
        it. Those rows stay exactly as they are and keep whoever is in them; agents added
        from here on sit on the bench. It is the one row the system makes for itself, and
        what entitles it to: nobody designed this row and nobody can (FR-007l).

        Takes the roster it was read from rather than reading it again: its caller needs the
        same rows to find the leader, and one transaction asking the same question twice is
        two chances for the two answers to be written against.
        """
        bench = next(
            (r for r in roles if r.key == MEMBERS_ROLE_KEY and not r.is_leader), None
        )
        if bench is not None:
            return bench
        return await uow.roles.add(
            Role(
                project_id=project_id,
                key=MEMBERS_ROLE_KEY,
                title=MEMBERS_ROLE_TITLE,
                seats=1,
                description=MEMBERS_ROLE_DESCRIPTION,
                created_at=utcnow(),
            )
        )

    async def seat_leader(
        self,
        project_id: UUID,
        marius_id: UUID,
        *,
        granted_by_user_id: str | None = None,
    ) -> SeatGrantView:
        """Put an agent in this project's leader seat.

        The one seat in the system that is a *position* and not just a place to be: the
        Leader coordinates the project, which is why Constitution V keeps it while every
        other role goes. Seating the agent already there is a no-op; a second agent is
        refused, because a project with two Leaders has none.

        An agent already on the bench is refused too, the same way `add_member` refuses one
        that already leads: it is on this project once, and the way to move it is to take it
        off the bench first.
        """
        return await self.grant_seat(
            project_id,
            LEADER_ROLE_KEY,
            marius_id,
            system=True,
            granted_by_user_id=granted_by_user_id,
        )

    async def add_member(
        self,
        project_id: UUID,
        marius_id: UUID,
        *,
        granted_by_user_id: str | None = None,
    ) -> SeatGrantView:
        """Put an agent on this project — the whole of it, in one step (FR-007l).

        Nothing here asks what the agent will *be* on this project, and that is the point.
        The old road went through a role: the patron wrote a title and a description of the
        work, then seated somebody under it — a second description of behaviour beside the
        instructions already written on the agent, kept by hand, drifting from them.

        Its own transaction rather than `grant_seat`, for one reason: the bench has no
        capacity. `grant_seat` refuses an agent when a role is full, which is the right
        answer for a seat that was promised to exactly one agent and the wrong one here —
        there is no number of members a project was promised.

        Idempotent: an agent already on the bench gets its seat back rather than a second
        row. An agent holding the leader seat is refused — it is already on this project,
        and the honest fix is to say so, not to put it in two places at once. `grant_seat`
        refuses the mirror of it, so neither door can seat one agent twice.
        """
        now = utcnow()
        async with self._uow() as uow:
            project = await uow.projects.get(project_id)
            if project is None:
                raise NotFound("project_not_found")
            agent = await uow.mariuses.get(marius_id)
            # Same refusal as *no such agent*, on purpose: an agent the caller may not see
            # reads the same either way (Constitution I).
            if agent is None or agent.workspace_id != project.workspace_id:
                raise NotFound("agent_not_found")
            roles = await uow.roles.list_by_project(project_id)
            bench = await self._bench(uow, project_id, roles)
            seated = await uow.seat_grants.list_by_project(project_id)
            leaders = leader_role_ids(roles)
            keys = {r.id: r.key for r in roles}
            for g in seated:
                if g.marius_id != marius_id:
                    continue
                if g.role_id in leaders:
                    raise BadRequest("agent_leads_this_project")
                # The seat it actually holds, named by the row it is on rather than by the
                # door that was knocked on. Those are the same row for every project made
                # since the bench existed; on one made before, the agent may be sitting on a
                # worker role somebody typed, and answering "members" would describe a seat
                # that is not the one it has.
                return self._seat_view(g, keys.get(g.role_id, MEMBERS_ROLE_KEY))
            grant = SeatGrant(
                project_id=project_id,
                role_id=bench.id,
                marius_id=marius_id,
                granted_by_user_id=granted_by_user_id,
                granted_at=now,
                created_at=now,
            )
            await uow.seat_grants.add(grant)
            flipped = await self._recompute_active(uow, project)
            await uow.commit()

        if flipped:
            await self._announce_planning(project_id)
        return self._seat_view(grant, MEMBERS_ROLE_KEY)

    async def remove_member(self, project_id: UUID, marius_id: UUID) -> SeatGrantView:
        """Take an agent off this project. Refuses if it is not on the bench.

        The Leader is not reachable from here, and there is no door that is: a project
        without a Leader is a project nothing drives, so the way to change who leads is to
        decide that when the project is set up.
        """
        return await self.revoke_seat_by_role(
            project_id, marius_id, MEMBERS_ROLE_KEY, system=True
        )

    # ── system-only seat grants ─────────────────────────────────────────────────
    async def grant_seat(
        self,
        project_id: UUID,
        role_key: str,
        marius_id: UUID,
        *,
        system: bool = False,
        granted_by_user_id: str | None = None,
    ) -> SeatGrantView:
        """Seat a Marius. SYSTEM-ONLY: a non-system caller is rejected (LLD §3.3).

        Re-evaluates activation after the grant. Returns the seat.

        Seating the same agent in the same role twice returns the seat it already has
        rather than writing a second row. It used to write one, and two rows for one agent
        then counted as two filled seats — a role with two seats read as full with one
        agent in it. One agent, one seat, one row.

        ``granted_by_user_id`` records **which patron** put this agent here (FR-034) —
        the one who will have to sign for its output. Captured at the moment of the grant
        because it cannot be reconstructed afterwards: today it happens to equal the
        workspace owner, and a later guess would be indistinguishable from a fact.
        """
        if not system:
            raise SystemOnlyOperation("seat_grants_system_only")
        now = utcnow()
        async with self._uow() as uow:
            project = await uow.projects.get(project_id)
            if project is None:
                raise NotFound("project_not_found")
            role = await self._role_by_key(uow, project_id, role_key)
            # The agent has to belong to this project's workspace. Checked here because
            # this is where a seat is created, and a seat across the boundary is what left
            # an agent's rows reachable from a workspace that does not own it: deleting the
            # agent's own workspace then hit a seat in somebody else's project, which the
            # foreign key now refuses outright. Same refusal as *no such agent*, on
            # purpose — an agent the caller may not see reads the same either way
            # (Constitution I).
            agent = await uow.mariuses.get(marius_id)
            if agent is None or agent.workspace_id != project.workspace_id:
                raise NotFound("agent_not_found")
            seated = await uow.seat_grants.list_by_project(project_id)
            existing = next(
                (g for g in seated if g.role_id == role.id and g.marius_id == marius_id),
                None,
            )
            if existing is not None:
                return self._seat_view(existing, role_key)
            # One agent, one seat on a project — and the rule has to be read from *every*
            # row, not just the one being granted. The check above only sees a second row
            # under the same role; an agent already on the bench asking for the leader seat
            # is a different role, so it passed, and the project ended up with one agent
            # holding two seats: counted twice in `seats_filled`, drawn twice on the roster
            # screen. `add_member` refuses the same collision from the other side, and a
            # rule enforced in one direction is not a rule.
            #
            # Written over the roster rather than over `role_key` so it does not need to
            # know which row it is on: whatever rows a project has, an agent sits on one.
            if any(g.marius_id == marius_id for g in seated):
                raise BadRequest("agent_is_on_this_project")
            # `seats` is what the roster promised, so it has to be what the roster holds.
            # The unique constraint underneath stops *one agent* taking the same seat
            # twice; it says nothing about *two agents* in a one-seat role, which is the
            # half that decides who `leader_marius_id` returns.
            taken = sum(1 for g in seated if g.role_id == role.id)
            if taken >= role.seats:
                raise BadRequest("role_seats_full", role=role_key, seats=str(role.seats))
            grant = SeatGrant(
                project_id=project_id,
                role_id=role.id,
                marius_id=marius_id,
                granted_by_user_id=granted_by_user_id,
                granted_at=now,
                created_at=now,
            )
            await uow.seat_grants.add(grant)
            flipped = await self._recompute_active(uow, project)
            await uow.commit()

        if flipped:
            await self._announce_planning(project_id)
        return self._seat_view(grant, role_key)

    async def list_seat_grants(self, project_id: UUID) -> list[SeatGrantView]:
        async with self._uow() as uow:
            keys = {r.id: r.key for r in await uow.roles.list_by_project(project_id)}
            return [
                self._seat_view(g, keys.get(g.role_id, ""))
                for g in await uow.seat_grants.list_by_project(project_id)
            ]

    async def revoke_seat(self, grant_id: UUID, *, system: bool = False) -> SeatGrantView:
        """Vacate a seat. SYSTEM-ONLY. Activation never rolls back (LLD §4)."""
        if not system:
            raise SystemOnlyOperation("seat_revokes_system_only")
        async with self._uow() as uow:
            grant = await uow.seat_grants.get(grant_id)
            if grant is None:
                raise NotFound("seat_grant_not_found")
            role = await uow.roles.get(grant.role_id)
            await uow.seat_grants.remove(grant.id)
            await uow.commit()
            return self._seat_view(grant, role.key if role else "")

    async def revoke_seat_by_role(
        self,
        project_id: UUID,
        marius_id: UUID,
        role_key: str,
        *,
        system: bool = False,
    ) -> SeatGrantView:
        """Vacate the seat (marius, role) holds in a project. SYSTEM-ONLY (§3.3).

        The row goes rather than being marked spent. Nothing running reads a vacated seat,
        and one kept beside the live one is only ever a thing to filter out — which is a
        step every future reader has to remember and one of them will not.
        """
        if not system:
            raise SystemOnlyOperation("seat_revokes_system_only")
        async with self._uow() as uow:
            role = await self._role_by_key(uow, project_id, role_key)
            grants = await uow.seat_grants.list_by_project(project_id)
            grant = next(
                (
                    g
                    for g in grants
                    if g.marius_id == marius_id and g.role_id == role.id
                ),
                None,
            )
            if grant is None:
                raise NotFound("no_granted_seat")
            await uow.seat_grants.remove(grant.id)
            await uow.commit()
            return self._seat_view(grant, role_key)

    @staticmethod
    def _seat_view(grant: SeatGrant, role_key: str) -> SeatGrantView:
        return SeatGrantView(
            id=grant.id,
            project_id=grant.project_id,
            role_key=role_key,
            marius_id=grant.marius_id,
            granted_by_user_id=grant.granted_by_user_id,
            granted_at=grant.granted_at,
            created_at=grant.created_at,
        )

    # ── activation ──────────────────────────────────────────────────────────────
    async def recompute_active(self, project_id: UUID) -> bool:
        """Re-evaluate the activation predicate; flip SETUP→ACTIVE once. Returns True
        iff it just activated."""
        async with self._uow() as uow:
            project = await uow.projects.get(project_id)
            if project is None:
                raise NotFound("project_not_found")
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
                raise project_rules.InvalidPhaseTransition("leave_planning_via_plan_gate")
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
            raise NotFound("project_not_found")
        if project_rules.is_closed(project.status):
            raise ProjectClosed("project_closed")
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
