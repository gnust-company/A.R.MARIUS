"""Helpers for making agents in tests.

Creating an agent takes a name and a workplace and nothing else (FR-007g).

**Acting as an agent means holding a run.** `/agent/*` authenticates the run token
(FR-014g) and nothing else does — including the two onboarding routes, now that the
team-building interview is a run of its own (FR-040c). So a test that wants to call any of
those routes opens a run first: see ``invite_and_online``, which returns the token of the
run it opened, and ``tests/support/runs.py`` for the run itself.
"""

from __future__ import annotations

from uuid import UUID

from httpx import AsyncClient


async def ready_workplace(
    ws_id: str | UUID, *, cli_kind: str = "claude_code", machine_name: str = "test-box"
) -> str:
    """A linked machine with one ready workplace on it, written straight to the database.

    Every agent must be attached to a workplace at creation (FR-007f), so a test that wants
    an agent needs one of these first. The device flow that normally produces it is four
    round trips and is itself covered elsewhere; replaying it in every test that merely
    needs *an agent to exist* would make those tests about machine enrolment instead of
    about what they are actually checking.
    """
    from uuid import uuid4

    from armarius.infrastructure.daemon.models import MachineModel, WorkplaceModel
    from armarius.main import app
    from armarius.shared.clock import utcnow

    workspace_id = UUID(str(ws_id))
    now = utcnow()
    async with app.state.container.uow_factory() as uow:
        workspace = await uow.workspaces.get(workspace_id)
        assert workspace is not None, "no such workspace"
        session = uow._session  # noqa: SLF001 — the tests' own back door, as in app_db
        assert session is not None
        machine = MachineModel(
            id=uuid4(),
            workspace_id=workspace_id,
            owner_user_id=UUID(str(workspace.owner_user_id)),
            display_name=machine_name,
            token_hash=f"test-{uuid4().hex}",
            symlink_capable=True,
            # Beating as of now. Without this the fixture would be a machine that has never
            # once been heard from, which is a real state with a real meaning — every agent
            # on it offline (FR-006a) — and not the state any caller of this helper wants.
            last_heartbeat_at=now,
            created_at=now,
        )
        workplace = WorkplaceModel(
            id=uuid4(),
            workspace_id=workspace_id,
            machine_id=machine.id,
            cli_kind=cli_kind,
            ready=True,
            created_at=now,
        )
        session.add(machine)
        session.add(workplace)
        await uow.commit()
    return str(workplace.id)


async def invite_agent(
    c: AsyncClient,
    ws_id: str,
    h: dict,
    *,
    name: str = "Marin",
    adapter_type: str | None = "echo",
    workplace_id: str | None = None,
    is_workspace_agent: bool = False,
    instructions: str = "",
    description: str = "",
    skills: list[str] | None = None,
    skill_ids: list[str] | None = None,
) -> dict:
    """Add an agent over HTTP: a name and a workplace, which is all it takes (FR-007g).

    A workplace is created for the workspace when none is named, because an agent cannot be
    created without one (FR-007f) and most callers here care about the agent, not where it
    works.

    No role is taken. How an agent behaves comes from its instructions (Constitution V).

    **`adapter_type` moves the agent afterwards, over the same route a person would use.**
    Creating an agent takes no runtime: the workplace declares who carries the work, and a
    workplace is a CLI on a machine, so what this route makes is an agent whose turns happen
    on that machine. Most tests here are about something else entirely and need a runtime
    this process can carry out inside the call — so they get one, by the ordinary edit, and
    the two lines it takes are visible rather than hidden in a body field the schema ignored.
    Pass ``None`` to leave the agent where it was put, which is what a test about the road to
    a machine wants."""
    body: dict = {
        "name": name,
        "instructions": instructions,
        "description": description,
        "workplace_id": workplace_id or await ready_workplace(ws_id),
        "is_workspace_agent": is_workspace_agent,
    }
    if skills is not None:
        body["skills"] = skills
    if skill_ids is not None:
        body["skill_ids"] = skill_ids
    r = await c.post(f"/v1/workspaces/{ws_id}/mariuses", headers=h, json=body)
    assert r.status_code == 201, r.text
    made = r.json()
    if adapter_type is None or made["adapter_type"] == adapter_type:
        return made
    moved = await c.patch(
        f"/v1/workspaces/{ws_id}/mariuses/{made['id']}",
        headers=h,
        json={"adapter_type": adapter_type},
    )
    assert moved.status_code == 200, moved.text
    return moved.json()


async def invite_and_online(
    c: AsyncClient,
    ws_id: str,
    h: dict,
    *,
    name: str = "Marin",
    is_workspace_agent: bool = False,
    instructions: str = "",
    skill_ids: list[str] | None = None,
    task_id: str | None = None,
    project_id: str | None = None,
) -> tuple[str, str]:
    """Invite an agent, open a run for it, then hit /agent/me so it flips ONLINE.

    Returns ``(marius_id, run_token)`` — the token an agent is actually started with.

    With neither `task_id` nor `project_id` the run is **workspace-level**: the widest
    shape there is, and the right default for a test that is about something other than
    scope. Pass one or both when the test *is* about scope.
    """
    data = await invite_agent(
        c,
        ws_id,
        h,
        name=name,
        is_workspace_agent=is_workspace_agent,
        instructions=instructions,
        skill_ids=skill_ids,
    )
    mid = data["id"]
    from tests.support.runs import open_run

    run = await open_run(marius_id=mid, task_id=task_id, project_id=project_id)
    me = await c.get("/agent/me", headers=run.headers)
    assert me.status_code == 200, me.text
    return mid, run.token


async def make_agent(
    uow_factory,
    *,
    workspace_id: UUID,
    name: str,
    role: str = "",
    skills: list[str] | None = None,
    adapter_type: str = "echo",
    adapter_config: dict | None = None,
    skill_ids: list[str] | None = None,
    owner_user_id: str | None = None,
):
    """An agent that exists in the database, placed, without going through HTTP.

    This used to be ``MariusService.register`` — a second way to create an agent, sitting in
    the application layer where no route reached it. Only tests ever called it, and because
    it predated FR-007f it created agents with nowhere to work: the one shape the product is
    not allowed to produce. Keeping it there meant the rule held only on the path somebody
    happened to be looking at, and the day a route was wired to the other path it would have
    broken silently. It lives here now, where being test scaffolding is the honest
    description of it, and the product has exactly one way to make an agent.

    It still places what it creates. A fixture that skips the placement would hand every test
    a state the product cannot reach, and tests built on impossible states stop being
    evidence about the product.
    """
    from uuid import uuid4

    from armarius.domain.entities.marius import Marius
    from armarius.infrastructure.daemon.models import MachineModel, WorkplaceModel
    from armarius.infrastructure.database.models import UserModel
    from armarius.shared.clock import utcnow
    from armarius.shared.errors import NotFound

    now = utcnow()
    async with uow_factory() as uow:
        workspace = await uow.workspaces.get(workspace_id)
        if workspace is None:
            raise NotFound("workspace_not_found")

        session = uow._session  # noqa: SLF001 — the tests' own back door, as in app_db
        assert session is not None

        # A machine belongs to a person. Service-level tests build their workspace directly
        # rather than by registering, so there may be no person yet; give them one instead of
        # making the column nullable, which would weaken the schema to suit a fixture.
        owner_id = _as_uuid(workspace.owner_user_id)
        if owner_id is None:
            owner_id = uuid4()
            session.add(
                UserModel(
                    id=owner_id,
                    email=f"{owner_id}@fixture.test",
                    username=str(owner_id),
                    full_name="Fixture Patron",
                    hashed_password="x",
                    created_at=now,
                    updated_at=now,
                )
            )
            await session.flush()

        machine = MachineModel(
            id=uuid4(),
            workspace_id=workspace_id,
            owner_user_id=owner_id,
            display_name=f"box-for-{name}",
            token_hash=f"test-{uuid4().hex}",
            symlink_capable=True,
            # Beating as of now, for the reason `ready_workplace` above beats: a machine
            # that has never once been heard from is a real state with a real meaning —
            # every agent on it offline (FR-006a) — and not the state a caller asking for
            # *an agent that exists* is asking for. Without this the helper handed out
            # agents that read as placed and answered no wakes.
            last_heartbeat_at=now,
            created_at=now,
        )
        workplace = WorkplaceModel(
            id=uuid4(),
            workspace_id=workspace_id,
            machine_id=machine.id,
            cli_kind="claude_code",
            ready=True,
            created_at=now,
        )
        session.add(machine)
        session.add(workplace)
        await session.flush()

        marius = Marius(
            workspace_id=workspace_id,
            name=name,
            role=role,
            skills=skills or [],
            skill_ids=skill_ids or [],
            adapter_type=adapter_type,
            adapter_config=adapter_config or {},
            owner_user_id=owner_user_id,
        )
        created = await uow.mariuses.add(marius)
        await uow.placements.attach(created.id, workspace_id, workplace.id)
        await uow.commit()
        return created


def _as_uuid(value) -> UUID | None:
    """The value if it is a usable id, None if there is nothing there to use."""
    if value is None:
        return None
    try:
        return UUID(str(value))
    except (ValueError, AttributeError, TypeError):
        return None
