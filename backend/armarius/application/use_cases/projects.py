"""Project & roster use cases (LLD §3.1, §4) — the roster-driven project lifecycle.

Three responsibilities the application layer owns on top of the pure rules in
`domain.services.project_rules`:
  - **create with the hard rule** — a project is born with a roster that has exactly one
    leader seat and at least one worker role (`validate_plan`); it starts in SETUP.
  - **system-only seat grants** — only the system assigns a Marius to a seat; every grant
    re-evaluates activation.
  - **activation** — `recompute_active` flips SETUP→ACTIVE once every seat is granted and
    every seated agent is ONLINE; it never rolls back.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from uuid import UUID

from armarius.application.use_cases.types import UowFactory
from armarius.domain.entities.project import Project, ProjectStatus
from armarius.domain.entities.role import Role
from armarius.domain.entities.seat_grant import SeatGrant, SeatGrantStatus
from armarius.domain.services import project_rules
from armarius.shared.clock import utcnow


class SystemOnlyOperation(Exception):
    """Raised when a seat grant/revoke is attempted by a non-system actor (LLD §3.3)."""


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
    responsibilities: str = ""
    skill_ids: list[str] = field(default_factory=list)


class ProjectService:
    def __init__(self, uow_factory: UowFactory) -> None:
        self._uow = uow_factory

    # ── create with the hard roster rule ────────────────────────────────────────
    async def create_project(
        self,
        workspace_id: UUID,
        name: str,
        *,
        roles: Sequence[RoleSpec],
        description: str | None = None,
        objective: str | None = None,
        created_by_user_id: str | None = None,
    ) -> Project:
        """Create a SETUP project with its roster. Raises InvalidProjectPlan if the
        roster violates the leader/worker rule; LookupError if the workspace is gone."""
        draft_roles = [self._role_from_spec(spec) for spec in roles]
        project_rules.validate_plan(draft_roles)  # hard rule — raises InvalidProjectPlan

        now = utcnow()
        async with self._uow() as uow:
            if await uow.workspaces.get(workspace_id) is None:
                raise LookupError("workspace not found")
            project = Project(
                workspace_id=workspace_id,
                name=name,
                slug=_slugify(name),
                description=description,
                objective=objective,
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
            responsibilities=spec.responsibilities,
            skill_ids=list(spec.skill_ids),
        )

    # ── roster CRUD ─────────────────────────────────────────────────────────────
    async def list_roles(self, project_id: UUID) -> Sequence[Role]:
        async with self._uow() as uow:
            return await uow.roles.list_by_project(project_id)

    async def add_role(self, project_id: UUID, spec: RoleSpec) -> Role:
        async with self._uow() as uow:
            if await uow.projects.get(project_id) is None:
                raise LookupError("project not found")
            role = self._role_from_spec(spec)
            role.project_id = project_id
            role.created_at = utcnow()
            created = await uow.roles.add(role)
            await uow.commit()
            return created

    async def update_role(
        self,
        role_id: UUID,
        *,
        title: str | None = None,
        seats: int | None = None,
        description: str | None = None,
        responsibilities: str | None = None,
        skill_ids: list[str] | None = None,
    ) -> Role:
        async with self._uow() as uow:
            role = await uow.roles.get(role_id)
            if role is None:
                raise LookupError("role not found")
            if title is not None:
                role.title = title
            if seats is not None:
                role.seats = seats
            if description is not None:
                role.description = description
            if responsibilities is not None:
                role.responsibilities = responsibilities
            if skill_ids is not None:
                role.skill_ids = skill_ids
            updated = await uow.roles.update(role)
            await uow.commit()
            return updated

    async def remove_role(self, role_id: UUID) -> None:
        async with self._uow() as uow:
            await uow.roles.remove(role_id)
            await uow.commit()

    # ── system-only seat grants ─────────────────────────────────────────────────
    async def grant_seat(
        self,
        project_id: UUID,
        role_key: str,
        marius_id: UUID,
        *,
        system: bool = False,
    ) -> SeatGrant:
        """Seat a Marius. SYSTEM-ONLY: a non-system caller is rejected (LLD §3.3).

        Re-evaluates activation after the grant. Returns the new grant.
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
                granted_at=now,
                created_at=now,
            )
            await uow.seat_grants.add(grant)
            await self._recompute_active(uow, project)
            await uow.commit()
            return grant

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
            return flipped

    @staticmethod
    async def _recompute_active(uow, project: Project) -> bool:
        roles = await uow.roles.list_by_project(project.id)
        grants = await uow.seat_grants.list_by_project(project.id)
        liveness_by_marius = {}
        for g in grants:
            if g.status != SeatGrantStatus.GRANTED or g.marius_id is None:
                continue
            marius = await uow.mariuses.get(g.marius_id)
            if marius is not None:
                liveness_by_marius[g.marius_id] = marius.liveness
        return project_rules.recompute_active(project, roles, grants, liveness_by_marius)
