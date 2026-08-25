"""Creating an agent — the one path there is (FR-007g, FR-007h, FR-007i, FR-007j).

Four things go in: a name, what the agent is told to be, what it can do, and where it works.
The tests here are about what the create path refuses, what it writes, and what it does not:
there is no gateway to probe, no key to store, and no prompt pushed at anybody.
"""

from __future__ import annotations

import pytest

from armarius.application.use_cases.enrollment import (
    AgentService,
    NameTaken,
    PlacementNotReady,
)
from armarius.domain.entities.marius import InviteStatus
from armarius.domain.entities.placement import Placement
from armarius.domain.entities.workspace import Workspace
from armarius.shared.errors import NotFound
from tests.support.fakes import FakeUowFactory, a_placement


def _world() -> tuple[FakeUowFactory, Workspace, Placement]:
    """A workspace with somewhere to put an agent.

    The placement comes with it because an agent cannot be created without one (FR-007f) —
    every test here would otherwise have to say so itself.
    """
    factory = FakeUowFactory()
    ws = Workspace(name="Studio", slug="studio", owner_user_id="u1")
    factory.store.workspaces[ws.id] = ws
    return factory, ws, a_placement(factory, ws.id)


async def test_a_name_and_a_place_is_the_whole_of_it() -> None:
    factory, ws, place = _world()

    marius = await AgentService(factory).create(ws.id, "Marin", placement_id=place.id)

    assert marius.name == "Marin"
    assert marius.workspace_id == ws.id
    # Nothing was collected about how to reach the agent, because nothing reaches out to it.
    assert marius.adapter_config == {}
    assert factory.store.attachments[marius.id] == place.id


async def test_instructions_are_kept_and_description_is_kept_apart() -> None:
    factory, ws, place = _world()

    marius = await AgentService(factory).create(
        ws.id,
        "Marin",
        placement_id=place.id,
        instructions="Always write the test first.",
        description="The one who keeps us honest.",
    )

    # Two fields rather than one, and the split is the point: instructions go down to the
    # agent on every run (FR-007i), the description never does (FR-007j). One field would
    # make a note written for the team into an order given to the agent.
    assert marius.instructions == "Always write the test first."
    assert marius.description == "The one who keeps us honest."


async def test_two_agents_in_one_workspace_cannot_share_a_name() -> None:
    factory, ws, place = _world()
    svc = AgentService(factory)
    await svc.create(ws.id, "Marin", placement_id=place.id)

    with pytest.raises(NameTaken):
        await svc.create(ws.id, "Marin", placement_id=place.id)

    # And the refusal left nothing behind: a half-made agent would have burned the name it
    # was refused for.
    assert len(factory.store.mariuses) == 1


async def test_the_name_check_does_not_care_about_case_or_stray_spaces() -> None:
    factory, ws, place = _world()
    svc = AgentService(factory)
    await svc.create(ws.id, "Marin", placement_id=place.id)

    # "marin" and "Marin " are the same name to a person calling one of them by voice or by
    # typing it, which is the only thing this rule exists to protect.
    with pytest.raises(NameTaken):
        await svc.create(ws.id, "  marin ", placement_id=place.id)


async def test_the_same_name_in_another_workspace_is_fine() -> None:
    factory, ws, place = _world()
    other = Workspace(name="Other", slug="other", owner_user_id="u2")
    factory.store.workspaces[other.id] = other
    other_place = a_placement(factory, other.id)
    svc = AgentService(factory)

    await svc.create(ws.id, "Marin", placement_id=place.id)
    twin = await svc.create(other.id, "Marin", placement_id=other_place.id)

    # The rule is about who answers when you call a name *here*. Two workspaces are two
    # rooms; a name shared across them confuses nobody.
    assert twin.name == "Marin"


async def test_an_agent_cannot_be_created_with_nowhere_to_work() -> None:
    factory, ws, _place = _world()

    with pytest.raises(TypeError):
        await AgentService(factory).create(ws.id, "Marin")  # type: ignore[call-arg]


async def test_a_placement_that_cannot_take_work_is_refused_with_the_reason() -> None:
    factory, ws, _ = _world()
    closed = a_placement(factory, ws.id, ready=False, not_ready_reason="cli_removed")

    with pytest.raises(PlacementNotReady) as caught:
        await AgentService(factory).create(ws.id, "Marin", placement_id=closed.id)

    # The reason travels with the refusal: "pick another one" and "fix this one" are
    # different instructions, and only the person on the other end can act on either.
    assert caught.value.params["reason"] == "cli_removed"
    assert not factory.store.mariuses


async def test_a_placement_in_another_workspace_reads_exactly_like_no_placement() -> None:
    factory, ws, _ = _world()
    other = Workspace(name="Other", slug="other", owner_user_id="u2")
    factory.store.workspaces[other.id] = other
    theirs = a_placement(factory, other.id)

    with pytest.raises(NotFound) as caught:
        await AgentService(factory).create(ws.id, "Marin", placement_id=theirs.id)
    assert caught.value.code == "placement_not_found"

    # Constitution I: not-yours must be indistinguishable from not-there. A different
    # refusal here would confirm that somebody else's workplace exists.
    from uuid import uuid4

    with pytest.raises(NotFound) as nowhere:
        await AgentService(factory).create(ws.id, "Marin", placement_id=uuid4())
    assert nowhere.value.code == caught.value.code


async def test_an_unknown_workspace_is_not_found() -> None:
    factory, ws, place = _world()
    from uuid import uuid4

    with pytest.raises(NotFound):
        await AgentService(factory).create(uuid4(), "Marin", placement_id=place.id)


async def test_the_agent_is_live_the_moment_it_is_made() -> None:
    factory, ws, place = _world()

    marius = await AgentService(factory).create(ws.id, "Marin", placement_id=place.id)

    # There is no approval step and nothing to wait for: the person adding the agent is the
    # one who would have approved it.
    assert marius.invite_status == InviteStatus.APPROVED
