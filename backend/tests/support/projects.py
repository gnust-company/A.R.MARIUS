"""Helpers for putting a project past the plan gate (spec 001 FR-003).

A real task now only exists once the patron has approved the plan. Most tests are about
something else entirely — dependency gates, artifacts, wake routing — and would otherwise
each have to replay the whole context → plan → approve dance before they can create the
one task they actually care about. That would test the plan gate a hundred times and the
thing under test once.

These helpers move a project straight to *operating* at the storage level. The gate itself
is proven where it belongs: `test_project_phases.py` (the rule) and `test_plan_api.py`
(the whole loop over HTTP).
"""

from __future__ import annotations

from uuid import UUID

from armarius.domain.entities.project import ProjectStatus


async def force_phase(
    uow_factory, project_id: UUID | str, phase: ProjectStatus = ProjectStatus.OPERATING
) -> None:
    """Set a project's phase directly, bypassing the transition table."""
    async with uow_factory() as uow:
        project = await uow.projects.get(UUID(str(project_id)))
        assert project is not None, f"project {project_id} not found"
        project.status = phase
        await uow.projects.update(project)
        await uow.commit()


async def force_operating(project_id: UUID | str) -> None:
    """Same, for HTTP-level tests that drive the global app rather than a UoW fixture."""
    from armarius.main import app

    await force_phase(app.state.container.uow_factory, project_id)
