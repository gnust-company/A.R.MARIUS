"""HTTP-level helpers for the operator-invite flow (issue #63).

Inviting an agent now mints the token at invite time and pushes a setup prompt over the
agent's gateway — the token is **never** returned by the API (it is a secret). Tests that
need to act as the agent (e.g. call ``/agent/me`` to flip it ONLINE) read the token back
from the repo via ``agent_token_for``.
"""

from __future__ import annotations

from uuid import UUID

from httpx import AsyncClient

# A gateway the echo adapter is happy with (its test_environment is always ok). The values
# are placeholders — the echo runtime ignores them; they just have to be non-empty.
GATEWAY_URL = "http://gateway.test"
GATEWAY_KEY = "test-key"


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
    adapter_type: str = "echo",
    gateway_url: str = GATEWAY_URL,
    api_key: str = GATEWAY_KEY,
    workplace_id: str | None = None,
    is_workspace_agent: bool = False,
    skills: list[str] | None = None,
    skill_ids: list[str] | None = None,
) -> dict:
    """Invite an agent with operator-supplied gateway creds → APPROVED + setup pushed.

    A workplace is created for the workspace when none is named, because an agent cannot be
    created without one (FR-007f) and most callers here care about the agent, not where it
    works.

    Role is intentionally not taken — it is a project-roster concept (#63)."""
    body: dict = {
        "name": name,
        "adapter_type": adapter_type,
        "gateway_url": gateway_url,
        "api_key": api_key,
        "workplace_id": workplace_id or await ready_workplace(ws_id),
        "is_workspace_agent": is_workspace_agent,
    }
    if skills is not None:
        body["skills"] = skills
    if skill_ids is not None:
        body["skill_ids"] = skill_ids
    r = await c.post(f"/v1/workspaces/{ws_id}/mariuses", headers=h, json=body)
    assert r.status_code == 201, r.text
    return r.json()


async def agent_token_for(marius_id: str | UUID) -> str:
    """Read an agent's minted token from the repo (the API never exposes it)."""
    from armarius.main import app

    async with app.state.container.uow_factory() as uow:
        marius = await uow.mariuses.get(UUID(str(marius_id)))
    assert marius is not None and marius.agent_token
    return marius.agent_token


async def invite_and_online(
    c: AsyncClient,
    ws_id: str,
    h: dict,
    *,
    name: str = "Marin",
    is_workspace_agent: bool = False,
    skill_ids: list[str] | None = None,
) -> tuple[str, str]:
    """Invite with creds, then hit /agent/me so the agent flips ONLINE.

    Returns ``(marius_id, agent_token)``.
    """
    data = await invite_agent(
        c,
        ws_id,
        h,
        name=name,
        is_workspace_agent=is_workspace_agent,
        skill_ids=skill_ids,
    )
    mid = data["id"]
    token = await agent_token_for(mid)
    me = await c.get("/agent/me", headers={"Authorization": f"Bearer {token}"})
    assert me.status_code == 200, me.text
    return mid, token
