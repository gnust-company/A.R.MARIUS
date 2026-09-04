"""Workspace, Project and Marius (directory) endpoints."""

from __future__ import annotations

from collections.abc import Sequence
from uuid import UUID

from fastapi import APIRouter

from armarius.domain.entities.marius import Marius
from armarius.infrastructure.daemon.workplaces import LinkedMachine
from armarius.presentation.api.auth import CurrentUser
from armarius.presentation.container import Container
from armarius.presentation.deps import ContainerDep
from armarius.presentation.schemas import (
    CreateLabelIn,
    CreateWorkspaceIn,
    ImportSkillIn,
    InstallSkillsIn,
    InstallSkillsOut,
    LabelOut,
    MachineOut,
    MachineWorkplaceOut,
    ManualSkillIn,
    MariusCreatedOut,
    MariusOut,
    PlacementOptionOut,
    RegisterMariusIn,
    ResidentAgentOut,
    RunOut,
    SkillOut,
    UpdateMachineIn,
    UpdateMariusIn,
    UpdateSkillIn,
    UpdateWorkspaceIn,
    WorkplaceChoiceOut,
    WorkspaceOut,
)
from armarius.shared.errors import CodedError, NotFound

router = APIRouter(prefix="/v1", tags=["workspaces"])


@router.post("/workspaces", response_model=WorkspaceOut, status_code=201)
async def create_workspace(
    body: CreateWorkspaceIn, container: ContainerDep, user: CurrentUser
) -> WorkspaceOut:
    ws = await container.workspaces.create_workspace(body.name, owner_user_id=str(user.id))
    return WorkspaceOut.model_validate(ws)


@router.get("/workspaces", response_model=list[WorkspaceOut])
async def list_workspaces(container: ContainerDep, user: CurrentUser) -> list[WorkspaceOut]:
    """List workspaces OWNED by the current user (multi-tenant scoped)."""
    items = await container.workspaces.list_workspaces(owner_user_id=str(user.id))
    return [WorkspaceOut.model_validate(w) for w in items]


@router.patch("/workspaces/{workspace_id}", response_model=WorkspaceOut)
async def rename_workspace(
    workspace_id: UUID,
    body: UpdateWorkspaceIn,
    container: ContainerDep,
    user: CurrentUser,
) -> WorkspaceOut:
    await _require_owned_workspace(container, user, workspace_id)
    ws = await container.workspaces.rename_workspace(workspace_id, body.name)
    return WorkspaceOut.model_validate(ws)


@router.delete("/workspaces/{workspace_id}", status_code=204)
async def delete_workspace(
    workspace_id: UUID, container: ContainerDep, user: CurrentUser
) -> None:
    await _require_owned_workspace(container, user, workspace_id)
    await container.workspaces.delete_workspace(workspace_id, owner_user_id=str(user.id))


# Project + roster + grant routes live in `presentation/api/projects.py`
# (the roster-driven ProjectService surface, API_CONTRACT §3).


async def _require_owned_workspace(container, user, workspace_id: UUID):
    ws = await container.workspaces.get_workspace(workspace_id)
    if ws is None or ws.owner_user_id != str(user.id):
        raise NotFound("workspace_not_found")
    return ws


@router.get("/workspaces/{workspace_id}/machines", response_model=list[MachineOut])
async def list_machines(
    workspace_id: UUID, container: ContainerDep, user: CurrentUser
) -> list[MachineOut]:
    """Every machine the patron has linked, and what is running where (FR-003, FR-033).

    Unlike the workplace picker beside it, this lists **everything** — including the
    workplaces that cannot take work. That is the point of the screen: a CLI that was
    uninstalled does not vanish from here, it turns red and keeps the agents attached to
    it, because those agents are attached for life (FR-007) and *who is stranded on this*
    is the question the person is actually asking.

    Owner-scoped through the same check every other workspace door uses, so somebody
    else's workspace reads exactly like one that does not exist (Constitution I).

    An empty list is a real answer: nobody has linked a machine yet.
    """
    await _require_owned_workspace(container, user, workspace_id)
    machines = await container.daemon_workplaces.list_machines(workspace_id)
    return [_machine_out(machine) for machine in machines]


@router.patch(
    "/workspaces/{workspace_id}/machines/{machine_id}", response_model=MachineOut
)
async def update_machine(
    workspace_id: UUID,
    machine_id: UUID,
    body: UpdateMachineIn,
    container: ContainerDep,
    user: CurrentUser,
) -> MachineOut:
    """Set how many runs this machine may hold at once (FR-008).

    The ceiling is the server's word, and the daemon's report of free slots is advice; the
    claim takes the smaller of the two (FR-008d). So this is the only number in that pair a
    person can move, and until this door existed it was a column with a default nobody could
    change — which made *the ceiling is adjustable* true of the schema and false of the
    product.

    **It takes effect on the next ask for work, not on the runs already out.** Lowering it
    does not recall anything: the number is read when a machine asks, and work past that
    point is being executed on a machine that was told to have it.

    A machine in a workspace that is not the caller's reads exactly like one that does not
    exist (Constitution I).
    """
    await _require_owned_workspace(container, user, workspace_id)
    machine = await container.daemon_workplaces.set_ceiling(
        workspace_id, machine_id, body.max_concurrent
    )
    if machine is None:
        raise NotFound("machine_not_found")
    return _machine_out(machine)


def _machine_out(machine: LinkedMachine) -> MachineOut:
    """One machine, shaped for the screen. One assembly, so two doors cannot disagree."""
    return MachineOut(
        id=machine.id,
        display_name=machine.display_name,
        platform=machine.platform,
        daemon_version=machine.daemon_version,
        last_heartbeat_at=machine.last_heartbeat_at,
        reachable=machine.reachable,
        max_concurrent=machine.max_concurrent,
        workplaces=[
            MachineWorkplaceOut(
                id=place.id,
                cli_kind=place.cli_kind,
                cli_version=place.cli_version,
                ready=place.ready,
                not_ready_reason=place.not_ready_reason,
                agents=[
                    ResidentAgentOut(id=agent.id, name=agent.name)
                    for agent in place.agents
                ],
            )
            for place in machine.workplaces
        ],
    )


@router.get(
    "/workspaces/{workspace_id}/workplaces",
    response_model=list[WorkplaceChoiceOut],
)
async def list_workplaces(
    workspace_id: UUID, container: ContainerDep, user: CurrentUser
) -> list[WorkplaceChoiceOut]:
    """The workplaces a new agent may be put on, in this workspace only (FR-007f).

    Owner-scoped through the same check every other workspace door uses, so a workspace
    that is not the caller's reads exactly like one that does not exist (Constitution I).

    An empty list is a real answer, not an error: it means this person has linked no machine
    yet, or every machine they linked has nothing runnable on it. The screen says so and
    points at linking a machine — refusing here would only turn a thing they can fix into an
    error they cannot read.
    """
    await _require_owned_workspace(container, user, workspace_id)
    offered = await container.daemon_workplaces.list_ready(workspace_id)
    return [
        WorkplaceChoiceOut(
            id=one.id,
            cli_kind=one.cli_kind,
            machine_name=one.machine_name,
            options=[
                PlacementOptionOut(
                    key=option.key, values=list(option.values), source=str(option.source.value)
                )
                for option in one.options
            ],
        )
        for one in offered
    ]


async def _with_offline_reason(
    container: Container, mariuses: Sequence[Marius]
) -> list[MariusOut]:
    """Render agents for the screen, each carrying why it has nowhere to work (FR-006c).

    Every route that hands an agent to a person goes through here, rather than only the
    one the roster happens to load from today. The screen keeps agents in a single store
    and writes back whatever the last call returned, so a route that skipped this would
    quietly blank the reason out the next time somebody renamed an agent.
    """
    reasons = await container.mariuses.offline_reasons([m.id for m in mariuses])
    return [
        MariusOut.model_validate(m).model_copy(update={"offline_reason": reasons.get(m.id)})
        for m in mariuses
    ]


@router.post(
    "/workspaces/{workspace_id}/mariuses",
    response_model=MariusCreatedOut,
    status_code=201,
)
async def create_marius(
    workspace_id: UUID,
    body: RegisterMariusIn,
    container: ContainerDep,
    user: CurrentUser,
) -> MariusCreatedOut:
    """Add an agent to the workspace (FR-007g).

    A name, what it is told to be, what it can do, and where it works. Nothing is dialled
    out to and nothing is pushed down: the machine the agent runs on comes and asks for
    work, so there is no setup step for this route to perform (FR-040a)."""
    await _require_owned_workspace(container, user, workspace_id)
    marius = await container.agents.create(
        workspace_id,
        body.name,
        # The workplace the person picked becomes, one layer down, a *placement*: the
        # business layer is not allowed to know that where an agent works is a CLI on a
        # machine (Constitution III). This line is where that translation happens, and it
        # is the only place it happens.
        placement_id=body.workplace_id,
        instructions=body.instructions,
        description=body.description,
        skills=body.skills,
        skill_ids=body.skill_ids,
        # Renamed on the way in: the caller says *runtime*, the business layer says what it
        # is allowed to know about — the place this agent works (Điều III).
        placement_options=body.runtime_options,
        owner_user_id=str(user.id),
    )
    if body.is_workspace_agent:
        # Seat the newcomer as host right away (#32) — an existing host is demoted to
        # a plain agent.
        await container.workspace_agent.designate(workspace_id, marius.id)
        marius = await container.mariuses.get(marius.id) or marius
    # Adding an agent is a connection step only (#43): it names no project and must
    # not conjure one. The patron commissions the first project explicitly (#49).
    await container.control_bus.publish(
        f"ws:{workspace_id}",
        "marius.status_changed",
        # *Created*, not *approved*. There was an approval step once and this said so; the
        # step went away, every agent has been live from its first second since, and the
        # word outlived the thing it described. Its pair on the other door is `deleted`,
        # and between them they are the whole of what this event has ever meant.
        {"marius_id": str(marius.id), "status": "created"},
    )
    rendered = (await _with_offline_reason(container, [marius]))[0]
    return MariusCreatedOut.model_validate(rendered.model_dump())


@router.get("/workspaces/{workspace_id}/mariuses", response_model=list[MariusOut])
async def list_directory(
    workspace_id: UUID, container: ContainerDep, user: CurrentUser
) -> list[MariusOut]:
    await _require_owned_workspace(container, user, workspace_id)
    items = await container.mariuses.list_directory(workspace_id)
    return await _with_offline_reason(container, items)


@router.get(
    "/workspaces/{workspace_id}/mariuses/{marius_id}/runs",
    response_model=list[RunOut],
)
async def list_marius_runs(
    workspace_id: UUID, marius_id: UUID, container: ContainerDep, user: CurrentUser
) -> list[RunOut]:
    """The agent's run history — the system↔agent interaction log the detail view tracks.

    Each run is one system-initiated dispatch to the agent (assignment, mention, commission,
    …) with its outcome; the durable per-run trace is fetched separately via `/v1/runs/{id}/
    events`. Owner-scoped: the workspace must be the caller's and the agent must live in it,
    so a cross-workspace id 404s rather than leaking another tenant's runs.
    """
    await _require_owned_workspace(container, user, workspace_id)
    marius = await container.mariuses.get(marius_id)
    if marius is None or marius.workspace_id != workspace_id:
        raise NotFound("agent_not_found")
    runs = await container.runs.list_by_marius(marius_id)
    return [RunOut.model_validate(r) for r in runs]


# ---------------------------------------------------------------------- labels
@router.get("/workspaces/{workspace_id}/labels", response_model=list[LabelOut])
async def list_labels(
    workspace_id: UUID, container: ContainerDep, user: CurrentUser
) -> list[LabelOut]:
    await _require_owned_workspace(container, user, workspace_id)
    items = await container.labels.list_labels(workspace_id)
    return [LabelOut.model_validate(label) for label in items]


@router.post(
    "/workspaces/{workspace_id}/labels", response_model=LabelOut, status_code=201
)
async def create_label(
    workspace_id: UUID,
    body: CreateLabelIn,
    container: ContainerDep,
    user: CurrentUser,
) -> LabelOut:
    await _require_owned_workspace(container, user, workspace_id)
    label = await container.labels.create(workspace_id, body.name, body.color)
    return LabelOut.model_validate(label)


@router.patch(
    "/workspaces/{workspace_id}/mariuses/{marius_id}",
    response_model=MariusOut,
)
async def update_marius(
    workspace_id: UUID,
    marius_id: UUID,
    body: UpdateMariusIn,
    container: ContainerDep,
    user: CurrentUser,
) -> MariusOut:
    await _require_owned_workspace(container, user, workspace_id)
    existing = await container.mariuses.get(marius_id)
    if existing is None or existing.workspace_id != workspace_id:
        raise NotFound("agent_not_found")
    marius = await container.mariuses.update(
        marius_id,
        name=body.name,
        role=body.role,
        skills=body.skills,
        skill_ids=body.skill_ids,
        adapter_type=body.adapter_type,
        adapter_config=body.adapter_config,
        # Renamed on the way in, the same as on the create route: the caller says *runtime*,
        # the business layer says what it is allowed to know about — the place this agent
        # works (Điều III).
        placement_options=body.runtime_options,
    )
    return (await _with_offline_reason(container, [marius]))[0]


@router.get(
    "/workspaces/{workspace_id}/mariuses/{marius_id}/options",
    response_model=list[PlacementOptionOut],
)
async def list_agent_options(
    workspace_id: UUID,
    marius_id: UUID,
    container: ContainerDep,
    user: CurrentUser,
) -> list[PlacementOptionOut]:
    """What may be changed about how this agent runs (FR-007k).

    Deliberately not read off `/workplaces`. That list exists for choosing where to *put* a
    new agent: it holds only the places still taking work, and it never says which place an
    existing agent sits at. Built on it, this screen would show *nothing to choose* for an
    agent whose CLI somebody uninstalled — when what that tool takes is perfectly well known
    and will matter again the moment it is put back.

    An empty list is an ordinary answer: this agent's place offers nothing to pick, and it
    runs on whatever its tool defaults to.
    """
    await _require_owned_workspace(container, user, workspace_id)
    existing = await container.mariuses.get(marius_id)
    if existing is None or existing.workspace_id != workspace_id:
        raise NotFound("agent_not_found")
    return [
        PlacementOptionOut(
            key=option.key, values=list(option.values), source=str(option.source.value)
        )
        for option in await container.mariuses.options_offered(marius_id)
    ]


@router.post(
    "/workspaces/{workspace_id}/mariuses/{marius_id}/designate",
    response_model=MariusOut,
)
async def designate_workspace_agent(
    workspace_id: UUID, marius_id: UUID, container: ContainerDep, user: CurrentUser
) -> MariusOut:
    """Hand the Workspace Agent seat to this Marius (#32). A sitting host is demoted
    to a plain agent — kept, not revoked. Idempotent for the current host."""
    await _require_owned_workspace(container, user, workspace_id)
    marius = await container.workspace_agent.designate(workspace_id, marius_id)
    await container.control_bus.publish(
        f"ws:{workspace_id}",
        "workspace_agent.designated",
        {"marius_id": str(marius_id)},
    )
    return (await _with_offline_reason(container, [marius]))[0]


@router.post(
    "/workspaces/{workspace_id}/mariuses/{marius_id}/install-skills",
    response_model=InstallSkillsOut,
)
async def install_skills(
    workspace_id: UUID,
    marius_id: UUID,
    body: InstallSkillsIn,
    container: ContainerDep,
    user: CurrentUser,
) -> InstallSkillsOut:
    """Link additional skills to an agent (issue #74, FR-011c).

    The skill_ids are merged into the agent's existing links (de-duped, order preserved).
    Nothing is pushed: a skill travels down with the work it is needed for, inside the claim
    packet the daemon fetches (FR-011b). Linking one is therefore the whole of the act — the
    agent installs it on its next run and confirms out of band via
    ``POST /agent/skills/{slug}/installed``.
    """
    await _require_owned_workspace(container, user, workspace_id)
    marius = await container.mariuses.get(marius_id)
    if marius is None or marius.workspace_id != workspace_id:
        raise NotFound("agent_not_found")

    # Merge requested skill_ids into the existing links (de-dup, preserve order).
    existing = list(marius.skill_ids)
    merged = list(dict.fromkeys([*existing, *body.skill_ids]))

    # Resolve merged → display NAMES (Marius.skills mirrors skill_ids so pills show), and the
    # REQUESTED subset → the skills to (re)push. Pushing EVERY requested skill — not only the
    # newly-linked ones — lets an already-linked skill whose content changed be reinstalled on
    # the agent; the old "newly-added only" behaviour meant a fixed skill never reached it (#74).
    resolved = list(await container.skills.resolve(merged))
    by_id = {str(sk.id): sk for sk in resolved}
    requested_skills = [by_id[i] for i in body.skill_ids if i in by_id]
    merged_names = [sk.name for sk in resolved]
    pushed_slugs = [sk.slug for sk in requested_skills]

    marius = await container.mariuses.update(
        marius_id, skill_ids=merged, skills=merged_names
    )

    # No install state is written here any more, because there is no install to be in a state
    # about. A skill granted to an agent is written onto the machine that runs it, as part of
    # the work packet, every run (FR-011b) — so *granted* and *present on disk* stopped being
    # two facts that could disagree, and the loop that used to reconcile them had nothing left
    # to reconcile (FR-011c).

    await container.control_bus.publish(
        f"ws:{workspace_id}",
        "marius.skills_updated",
        {"marius_id": str(marius_id), "installed": pushed_slugs},
    )
    return InstallSkillsOut(
        marius_id=marius.id,
        skill_ids=merged,
        installed=pushed_slugs,
    )


@router.delete(
    "/workspaces/{workspace_id}/mariuses/{marius_id}", status_code=204
)
async def delete_marius(
    workspace_id: UUID, marius_id: UUID, container: ContainerDep, user: CurrentUser
) -> None:
    """Remove an agent from the directory. The Workspace Agent can be removed too —
    doing so just vacates its host seat (#50)."""
    await _require_owned_workspace(container, user, workspace_id)
    marius = await container.mariuses.get(marius_id)
    if marius is None or marius.workspace_id != workspace_id:
        raise NotFound("agent_not_found")
    await container.mariuses.delete(marius_id)
    await container.control_bus.publish(
        f"ws:{workspace_id}",
        "marius.status_changed",
        {"marius_id": str(marius_id), "status": "deleted"},
    )


# ---------------------------------------------------------------------- skills
@router.get("/workspaces/{workspace_id}/skills", response_model=list[SkillOut])
async def list_skills(
    workspace_id: UUID, container: ContainerDep, user: CurrentUser
) -> list[SkillOut]:
    await _require_owned_workspace(container, user, workspace_id)
    items = await container.skills.list_skills(workspace_id)
    return [SkillOut.model_validate(s) for s in items]


@router.get(
    "/workspaces/{workspace_id}/skills/{skill_id}", response_model=SkillOut
)
async def get_skill(
    workspace_id: UUID, skill_id: UUID, container: ContainerDep, user: CurrentUser
) -> SkillOut:
    await _require_owned_workspace(container, user, workspace_id)
    skill = await container.skills.get_skill(skill_id)
    if skill is None or skill.workspace_id != workspace_id:
        raise NotFound("skill_not_found")
    return SkillOut.model_validate(skill)


@router.post(
    "/workspaces/{workspace_id}/skills/manual",
    response_model=SkillOut,
    status_code=201,
)
async def create_manual_skill(
    workspace_id: UUID, body: ManualSkillIn, container: ContainerDep, user: CurrentUser
) -> SkillOut:
    await _require_owned_workspace(container, user, workspace_id)
    skill = await container.skills.create_manual(
        workspace_id=workspace_id, name=body.name, description=body.description
    )
    return SkillOut.model_validate(skill)


@router.post(
    "/workspaces/{workspace_id}/skills/import",
    response_model=SkillOut,
    status_code=201,
)
async def import_skill(
    workspace_id: UUID, body: ImportSkillIn, container: ContainerDep, user: CurrentUser
) -> SkillOut:
    await _require_owned_workspace(container, user, workspace_id)
    try:
        skill = await container.skills.import_from_url(
            workspace_id=workspace_id, url=body.source_url
        )
    except CodedError as e:
        # The import failed on what the URL pointed at, so the answer is 404 — but the
        # reason travels with its code, not flattened into a sentence.
        raise NotFound(e.code, **e.params) from e
    return SkillOut.model_validate(skill)


@router.put(
    "/workspaces/{workspace_id}/skills/{skill_id}", response_model=SkillOut
)
async def update_skill(
    workspace_id: UUID,
    skill_id: UUID,
    body: UpdateSkillIn,
    container: ContainerDep,
    user: CurrentUser,
) -> SkillOut:
    await _require_owned_workspace(container, user, workspace_id)
    existing = await container.skills.get_skill(skill_id)
    if existing is None or existing.workspace_id != workspace_id:
        raise NotFound("skill_not_found")
    skill = await container.skills.update_files(skill_id, body.files)
    return SkillOut.model_validate(skill)


@router.delete(
    "/workspaces/{workspace_id}/skills/{skill_id}", status_code=204
)
async def delete_skill(
    workspace_id: UUID, skill_id: UUID, container: ContainerDep, user: CurrentUser
) -> None:
    """Delete a workspace skill (built-in skills are protected)."""
    await _require_owned_workspace(container, user, workspace_id)
    skill = await container.skills.get_skill(skill_id)
    if skill is None or skill.workspace_id != workspace_id:
        raise NotFound("skill_not_found")
    await container.skills.delete_skill(skill_id)
