"""Composition root — wires infrastructure into application services (one place).

This is the only module allowed to know about both the application services and the
concrete infrastructure implementations.
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from armarius.application.ports.artifact_store import ArtifactStore
from armarius.application.ports.event_bus import EventBus
from armarius.application.use_cases.approvals import ApprovalService
from armarius.application.use_cases.artifacts import ArtifactService
from armarius.application.use_cases.auth import AuthService
from armarius.application.use_cases.enrollment import AgentService
from armarius.application.use_cases.inbox import InboxService
from armarius.application.use_cases.labels import LabelService
from armarius.application.use_cases.leader_chat import LeaderChatService
from armarius.application.use_cases.liveness import LivenessEngine
from armarius.application.use_cases.liveness_watchdog import LivenessWatchdog
from armarius.application.use_cases.mariuses import MariusService
from armarius.application.use_cases.onboarding_session import OnboardingService
from armarius.application.use_cases.orchestrator import OrchestrationLoop
from armarius.application.use_cases.plans import PlanService
from armarius.application.use_cases.projects import ProjectService
from armarius.application.use_cases.push_reason import PushReasonService
from armarius.application.use_cases.recovery import OfflineFalloutService, RecoveryEscalator
from armarius.application.use_cases.runs import RunQueryService
from armarius.application.use_cases.skills import SkillService
from armarius.application.use_cases.stall_watchdog import StallWatchdog
from armarius.application.use_cases.task_log import TaskLogService
from armarius.application.use_cases.tasks import TaskService
from armarius.application.use_cases.threads import ThreadService
from armarius.application.use_cases.trace_retention import TraceRetention
from armarius.application.use_cases.wake_engine import WakeEngine
from armarius.application.use_cases.workspace_agent import WorkspaceAgentService
from armarius.application.use_cases.workspaces import WorkspaceService
from armarius.domain.entities.project import ProjectThresholds
from armarius.infrastructure.adapters.daemon_adapter import DaemonAdapter
from armarius.infrastructure.adapters.echo import EchoAdapter
from armarius.infrastructure.adapters.registry import InMemoryAdapterRegistry
from armarius.infrastructure.daemon.claim import DaemonClaimService
from armarius.infrastructure.daemon.enrollment import DaemonEnrollmentService
from armarius.infrastructure.daemon.housekeeping import DaemonHousekeepingService
from armarius.infrastructure.daemon.link_guard import LinkDoorGuard
from armarius.infrastructure.daemon.liveness import DaemonLivenessProbe
from armarius.infrastructure.daemon.run_auth import RunTokenAuthenticator
from armarius.infrastructure.daemon.workplaces import DaemonWorkplaceService
from armarius.infrastructure.events.in_memory_bus import InMemoryEventBus
from armarius.infrastructure.events.task_trace import ControlBusTaskTrace
from armarius.infrastructure.events.topic_bus import TopicEventBus, machine_topic
from armarius.infrastructure.events.workspace_trace import ControlBusWorkspaceTrace
from armarius.infrastructure.persistence.unit_of_work import make_uow
from armarius.infrastructure.security.jwt import JWTService
from armarius.infrastructure.security.password import PasswordService
from armarius.infrastructure.store.local_store import LocalArtifactStore
from armarius.infrastructure.store.minio_store import MinioArtifactStore
from armarius.shared.config import settings


@dataclass
class Container:
    event_bus: EventBus
    control_bus: TopicEventBus
    registry: InMemoryAdapterRegistry
    wake_engine: WakeEngine
    workspaces: WorkspaceService
    workspace_agent: WorkspaceAgentService
    projects: ProjectService
    plans: PlanService
    onboarding: OnboardingService
    agents: AgentService
    leader_chat: LeaderChatService
    liveness: LivenessEngine
    liveness_watchdog: LivenessWatchdog
    orchestrator: OrchestrationLoop
    push_reasons: PushReasonService
    stall_watchdog: StallWatchdog
    #: The clock that forgets a run's log once it is past its keeping (FR-050).
    trace_retention: TraceRetention
    recovery: RecoveryEscalator
    inbox: InboxService
    labels: LabelService
    mariuses: MariusService
    tasks: TaskService
    approvals: ApprovalService
    task_logs: TaskLogService
    threads: ThreadService
    artifacts: ArtifactService
    artifact_store: ArtifactStore
    runs: RunQueryService
    auth: AuthService
    skills: SkillService
    jwt_service: JWTService
    daemon_claims: DaemonClaimService
    daemon_enrollment: DaemonEnrollmentService
    #: The counters in front of the three link doors (FR-001).
    daemon_link_guard: LinkDoorGuard
    daemon_housekeeping: DaemonHousekeepingService
    daemon_workplaces: DaemonWorkplaceService
    run_auth: RunTokenAuthenticator
    uow_factory: object


def _system_thresholds() -> ProjectThresholds:
    """The system floor for every timing knob (spec 001). Read the environment here, in
    the composition root, so no service below has to."""
    return ProjectThresholds(
        hang_suspect_seconds=settings.hang_suspect_seconds,
        hang_grace_seconds=settings.hang_grace_seconds,
        orchestration_cadence_seconds=settings.orchestration_cadence_seconds,
        due_soon_hours=tuple(settings.due_soon_hour_marks),
        patron_reminder_hours=tuple(settings.patron_reminder_hour_tiers),
        level1_recovery_attempts=settings.level1_recovery_attempts,
        rejection_round_cap=settings.rejection_round_cap,
        orchestration_wakes_per_hour=settings.orchestration_wakes_per_hour,
        orchestration_max_stretch=settings.orchestration_max_stretch,
        orchestration_max_interval_seconds=settings.orchestration_max_interval_seconds,
        orchestration_min_interval_seconds=settings.orchestration_min_interval_seconds,
        level2_handover_attempts=settings.level2_handover_attempts,
    )


def build_container() -> Container:
    uow_factory = make_uow

    event_bus = InMemoryEventBus()
    control_bus = TopicEventBus()

    registry = InMemoryAdapterRegistry()
    registry.register(EchoAdapter())

    store: ArtifactStore
    if settings.artifact_store_backend == "minio":
        store = MinioArtifactStore(
            endpoint=settings.minio_endpoint,
            access_key=settings.minio_access_key,
            secret_key=settings.minio_secret_key,
            bucket=settings.minio_bucket,
            secure=settings.minio_secure,
        )
    else:
        store = LocalArtifactStore(settings.artifact_store_path)

    jwt_service = JWTService()
    password_service = PasswordService()

    # Built before the services that need it — the Leader chat is also the project-level
    # wake path (spec 001), so ProjectService and PlanService both take it.
    liveness_for_chat = LivenessEngine(
        uow_factory,
        DaemonLivenessProbe(uow_factory),
        workspace_trace=ControlBusWorkspaceTrace(control_bus),
    )

    # Built before the wake engine: the engine hands an agent its skills as part of the
    # packet it composes, so it needs the one object that knows what a skill is.
    skills = SkillService(uow_factory)

    # One publisher for the per-task channel, shared: a run carried out in this process and a
    # run carried out on somebody's machine both appear on the same channel, so a screen
    # watching a task does not have to know which road its run took (FR-046, Constitution III).
    task_trace = ControlBusTaskTrace(control_bus)

    wake_engine = WakeEngine(
        uow_factory,
        registry,
        event_bus,
        run_timeout_seconds=settings.run_timeout_seconds,
        max_continuation_attempts=settings.wake_max_continuation_attempts,
        task_trace=task_trace,
        workspace_trace=ControlBusWorkspaceTrace(control_bus),
        skills=skills,
    )

    workspaces = WorkspaceService(uow_factory, skills)

    # The reminder ladder reads each project's own tiers (FR-065), but the full project
    # service needs the inbox — a genuine cycle. Broken with a second, thresholds-only
    # instance: `get_thresholds` is a pure read with no state behind it, so two objects
    # cannot disagree. Reordering instead would mean the inbox holding a half-built
    # project service, which is the same cycle with the failure moved to runtime.
    thresholds_reader = ProjectService(uow_factory, system_thresholds=_system_thresholds())
    inbox = InboxService(uow_factory, control_bus, projects=thresholds_reader)
    leader_chat = LeaderChatService(
        uow_factory,
        registry=registry,
        control_bus=control_bus,
        liveness=liveness_for_chat,
        base_url=settings.public_api_url,
        run_timeout_seconds=settings.run_timeout_seconds,
        # A turn of this chat can be taken on somebody's machine now, and a turn offered to a
        # machine that has none left is refused at the door. Closing that run is the same act
        # as closing any other, so it goes through the one object that knows what closing a
        # run means rather than through a second answer written here (FR-040b).
        close_run=wake_engine.conclude_run,
    )
    projects = ProjectService(
        uow_factory,
        system_thresholds=_system_thresholds(),
        control_bus=control_bus,
        inbox=inbox,
        leader_chat=leader_chat,
    )
    workspace_agent = WorkspaceAgentService(uow_factory)
    onboarding = OnboardingService(
        uow_factory,
        projects,
        workspace_agent,
        registry,
        # The interview's turn runs where this process cannot watch it, so the screen holding
        # the chat open is told to come back and read it (FR-040c).
        workspace_trace=ControlBusWorkspaceTrace(control_bus),
        # And a turn an in-process runtime carries out inside the dispatch is closed the same
        # way a turn on a machine is, through the one object that knows what closing a run
        # means. Two ways of ending a run would be two answers to what a finished run leaves
        # behind.
        close_run=wake_engine.conclude_run,
    )

    # The single writer of `task.drive` (FR-056). Built before the task service because
    # every status change settles its drive through this one object — two writers is how
    # a field comes to mean two different things.
    push_reasons = PushReasonService(
        uow_factory,
        projects,
        # One number wearing two hats, and this is the only place that can keep it one:
        # it is both how long a machine keeps work it has taken and how long the drive
        # on that work lives. FR-056c forbids tuning the two apart, so neither side owns
        # a default of its own — they are handed the same setting here.
        accept_grace_seconds=settings.run_claim_hold_seconds,
    )
    # The one door work goes out through (FR-053). Built after `push_reasons` because
    # it hands back what it takes away: a machine that loses its grip leaves a task
    # whose board still says a run is live on it, and the board should be told in
    # seconds rather than at the next sweep.
    async def nudge_machine(machine_id: UUID, workplace_id: UUID) -> None:
        """The push road (FR-055a): a signal, carrying no work and ordering nothing.

        Riding the same bus the browser streams ride, on a topic keyed to the one machine
        that can act on it. What the machine does with it is call the claim door — the same
        door it calls on its own rhythm — so a nudge that arrives twice costs one extra ask
        and nothing more.
        """
        await control_bus.publish(
            machine_topic(machine_id),
            "pending_work",
            {"workplace_id": str(workplace_id)},
        )

    async def show_run_event(
        run_id: UUID, seq: int, event_type: str, payload: dict
    ) -> None:
        """One event, put in front of both screens that could be watching this run.

        The run's own channel is the log a person opens to answer *what did this agent do*.
        The second reader is the project chat: a turn of it can be taken on a machine now, and
        without this line the patron would watch an empty box until the whole reply landed at
        once (FR-046, FR-040b). Wired separately from the task channel above because these
        runs have no task — a chat is about the project, not about a piece of work.
        """
        await event_bus.publish(
            run_id, {"type": event_type, "seq": seq, "payload": payload}
        )
        await leader_chat.run_event(run_id, event_type, payload)

    async def run_is_over(run_id: UUID) -> None:
        """Everyone owed the news that a run ended, other than the run loop itself.

        Second readers of one fact, not second decisions: a run may have been carrying a turn
        of a team-building interview or of the project chat, and a conversation left mid-turn
        is not rescued by anything the run loop does — it stays mid-turn and refuses the
        patron's every next message (FR-040c, FR-040e). Kept apart from the closing itself
        because a run ends by more than one road, and only one of them goes through the
        engine: the hung-run reaper writes its own ending, and these readers are owed that
        one too.
        """
        await onboarding.run_ended(run_id)
        await leader_chat.run_ended(run_id)

    async def close_run(run_id: UUID, **ending: object) -> None:
        """A run reported finished from a machine, and everyone who is owed that news.

        The wake engine is what *closing a run* means and stays the only thing that decides
        it. Told here rather than from inside the engine, because a chat is not something the
        run loop knows about.
        """
        await wake_engine.conclude_run(run_id, **ending)  # type: ignore[arg-type]
        await run_is_over(run_id)

    claims = DaemonClaimService(
        on_release=push_reasons.refresh,
        on_offer=nudge_machine,
        # The message and the skills are made up here, on the way out. The door itself only
        # knows a run changed hands; what that run is *about* comes from the layer that
        # knows the project, the agent and why it was woken (FR-011a, Constitution III).
        compose=wake_engine.compose_packet,
        # Each event put in front of anyone watching the task, on the same channel the
        # in-process path uses (FR-046). One channel, so a run carried out on somebody's
        # machine and a run carried out here are watched the same way.
        on_recorded=task_trace.publish,
        # The run's own channel, beside the task's. A person reading one run's log while it
        # happens is subscribed here, and until this existed only the in-process adapter fed
        # it — so a run on a real machine wrote a full record and streamed nothing (FR-046).
        on_run_event=show_run_event,
        # A run that has actually begun, said on the channel an agent's own screen holds
        # open. The in-process road announces this transition itself; without this line the
        # same run carried out on a machine sat at *queued* on screen for the whole time it
        # ran, and only moved when it ended (FR-080).
        on_start=wake_engine.run_started,
        # And the end of a run handed to the layer that decides what a task does next — the
        # follow-up wake above all, which is what stops a finished run leaving a task with
        # nothing scheduled to look at it again (FR-030a).
        on_finish=close_run,
    )
    registry.register(DaemonAdapter(claims))
    # Tasks and approvals are built here rather than inline below: the approval service
    # closes a task through the task service, so it needs the same instance the API uses.
    tasks = TaskService(
        uow_factory,
        wake_engine,
        leader_chat=leader_chat,
        task_logs=TaskLogService(uow_factory),
        control_bus=control_bus,
        inbox=inbox,
        push_reasons=push_reasons,
    )
    # One escalator, shared: the watchdog climbs the ladder and the Leader's recovery
    # endpoint clears it. Two instances would each hold their own idea of where a task
    # stands, and the rung the Leader answered would not be the rung the sweep reads.
    #
    # Built after the task service because the patron's answer to a Mức 3 letter changes
    # the task and closes the letter under one transaction, so it needs that same instance.
    recovery = RecoveryEscalator(
        uow_factory,
        projects,
        wakes=wake_engine,
        inbox=inbox,
        task_log=TaskLogService(uow_factory),
        control_bus=control_bus,
        leader_notifier=leader_chat,
        push_reasons=push_reasons,
        tasks=tasks,
        backoff_base_seconds=settings.level1_backoff_seconds,
    )

    liveness = liveness_for_chat
    liveness_watchdog = LivenessWatchdog(
        uow_factory,
        liveness,
        interval_seconds=settings.liveness_watchdog_interval_seconds,
        # The hung-run reaper rides this loop (FR-062): the same clock already asks
        # "has this agent gone quiet?", and a hung run is that question about a run.
        hang_suspect_seconds=settings.hang_suspect_seconds,
        hang_grace_seconds=settings.hang_grace_seconds,
        wakes=wake_engine,
        task_log=TaskLogService(uow_factory),
        push_reasons=push_reasons,
        workspace_trace=ControlBusWorkspaceTrace(control_bus),
        # Reaping is the **only** ending a hung run gets — it writes its own, without going
        # through the engine — so the conversations a run can be carrying have to be told
        # from here as well, or a chat whose turn hung waits for ever.
        run_ended=run_is_over,
    )
    # The Leader's controlled heartbeat (spec 001 FR-052 → FR-055). Ticks often and
    # cheaply; each project is swept on its own rhythm, and only a sweep that found
    # something costs the Leader a turn.
    orchestrator = OrchestrationLoop(
        uow_factory,
        projects,
        leader_notifier=leader_chat,
        # Every pass is announced on the project channel so the board's cadence block
        # stays current without asking again on a timer (FR-080, Constitution IV).
        control_bus=control_bus,
        interval_seconds=settings.orchestration_tick_seconds,
    )
    # The safety net (spec 001 FR-056 → FR-069). The watchdog only reads the clock on a
    # drive and hands what it finds to the recovery ladder. Detection and recovery are
    # split because detection has to keep working even when every recovery route is
    # broken — that is the failure it exists to survive.
    trace_retention = TraceRetention(uow_factory)
    stall_watchdog = StallWatchdog(
        uow_factory,
        push_reasons,
        task_log=TaskLogService(uow_factory),
        control_bus=control_bus,
        inbox=inbox,
        ladder=recovery,
        interval_seconds=settings.stall_scan_interval_seconds,
    )
    # An agent declared offline has fallout on the board (FR-064). Attached rather than
    # injected: the handler needs the Leader chat, and the Leader chat needs the liveness
    # engine — see `LivenessEngine.attach_fallout`.
    liveness.attach_fallout(
        OfflineFalloutService(
            uow_factory,
            inbox=inbox,
            task_log=TaskLogService(uow_factory),
            push_reasons=push_reasons,
            leader_notifier=leader_chat,
        )
    )

    return Container(
        event_bus=event_bus,
        control_bus=control_bus,
        registry=registry,
        wake_engine=wake_engine,
        workspaces=workspaces,
        workspace_agent=workspace_agent,
        projects=projects,
        plans=PlanService(
            uow_factory,
            control_bus=control_bus,
            inbox=inbox,
            leader_chat=leader_chat,
            task_logs=TaskLogService(uow_factory),
        ),
        onboarding=onboarding,
        agents=AgentService(uow_factory),
        leader_chat=leader_chat,
        liveness=liveness,
        liveness_watchdog=liveness_watchdog,
        orchestrator=orchestrator,
        push_reasons=push_reasons,
        stall_watchdog=stall_watchdog,
        trace_retention=trace_retention,
        recovery=recovery,
        inbox=inbox,
        labels=LabelService(uow_factory),
        mariuses=MariusService(uow_factory),
        tasks=tasks,
        approvals=ApprovalService(
            uow_factory,
            tasks=tasks,
            wake=wake_engine,
            task_logs=TaskLogService(uow_factory),
            control_bus=control_bus,
            # Asked one question, at one moment: is the deliverable still there when
            # somebody is about to sign for it (FR-069).
            artifact_store=store,
            # The patron refusing an output is the Leader's business too (FR-047, T189).
            leader_chat=leader_chat,
        ),
        task_logs=TaskLogService(uow_factory),
        threads=ThreadService(uow_factory, wake_engine, control_bus=control_bus),
        artifacts=ArtifactService(
            uow_factory,
            store,
            control_bus=control_bus,
            drive_refresh=push_reasons.refresh,
        ),
        artifact_store=store,
        runs=RunQueryService(uow_factory),
        auth=AuthService(uow_factory, workspaces, jwt_service, password_service),
        skills=skills,
        jwt_service=jwt_service,
        daemon_claims=claims,
        daemon_enrollment=DaemonEnrollmentService(),
        daemon_link_guard=LinkDoorGuard(),
        daemon_housekeeping=DaemonHousekeepingService(),
        daemon_workplaces=DaemonWorkplaceService(),
        run_auth=RunTokenAuthenticator(),
        uow_factory=uow_factory,
    )
