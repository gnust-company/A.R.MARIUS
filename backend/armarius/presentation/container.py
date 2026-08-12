"""Composition root — wires infrastructure into application services (one place).

This is the only module allowed to know about both the application services and the
concrete infrastructure implementations.
"""

from __future__ import annotations

from dataclasses import dataclass

from armarius.application.ports.artifact_store import ArtifactStore
from armarius.application.ports.event_bus import EventBus
from armarius.application.use_cases.approvals import ApprovalService
from armarius.application.use_cases.artifacts import ArtifactService
from armarius.application.use_cases.auth import AuthService
from armarius.application.use_cases.enrollment import InviteService
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
from armarius.application.use_cases.wake_engine import WakeEngine
from armarius.application.use_cases.workspace_agent import WorkspaceAgentService
from armarius.application.use_cases.workspaces import WorkspaceService
from armarius.domain.entities.project import ProjectThresholds
from armarius.infrastructure.adapters.echo import EchoAdapter
from armarius.infrastructure.adapters.hermes_gateway import HermesGatewayAdapter
from armarius.infrastructure.adapters.liveness_probe import GatewayHealthLivenessProbe
from armarius.infrastructure.adapters.registry import InMemoryAdapterRegistry
from armarius.infrastructure.events.in_memory_bus import InMemoryEventBus
from armarius.infrastructure.events.task_trace import ControlBusTaskTrace
from armarius.infrastructure.events.topic_bus import TopicEventBus
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
    invite: InviteService
    leader_chat: LeaderChatService
    liveness: LivenessEngine
    liveness_watchdog: LivenessWatchdog
    orchestrator: OrchestrationLoop
    push_reasons: PushReasonService
    stall_watchdog: StallWatchdog
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
    uow_factory: object


def _system_thresholds() -> ProjectThresholds:
    """The system floor for every timing knob (spec 001). Read the environment here, in
    the composition root, so no service below has to."""
    return ProjectThresholds(
        hang_suspect_seconds=settings.hang_suspect_seconds,
        hang_grace_seconds=settings.hang_grace_seconds,
        orchestration_cadence_seconds=settings.orchestration_cadence_seconds,
        task_silence_seconds=settings.task_silence_seconds,
        due_soon_hours=tuple(settings.due_soon_hour_marks),
        patron_reminder_hours=tuple(settings.patron_reminder_hour_tiers),
        level1_recovery_attempts=settings.level1_recovery_attempts,
        rejection_round_cap=settings.rejection_round_cap,
        orchestration_wakes_per_hour=settings.orchestration_wakes_per_hour,
    )


def build_container() -> Container:
    uow_factory = make_uow

    event_bus = InMemoryEventBus()
    control_bus = TopicEventBus()

    registry = InMemoryAdapterRegistry()
    registry.register(HermesGatewayAdapter())
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
        GatewayHealthLivenessProbe(registry),
        workspace_trace=ControlBusWorkspaceTrace(control_bus),
    )

    wake_engine = WakeEngine(
        uow_factory,
        registry,
        event_bus,
        run_timeout_seconds=settings.run_timeout_seconds,
        max_continuation_attempts=settings.wake_max_continuation_attempts,
        task_trace=ControlBusTaskTrace(control_bus),
        workspace_trace=ControlBusWorkspaceTrace(control_bus),
    )

    skills = SkillService(uow_factory)
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
        settings.public_api_url,
    )

    # The single writer of `task.drive` (FR-056). Built before the task service because
    # every status change settles its drive through this one object — two writers is how
    # a field comes to mean two different things.
    push_reasons = PushReasonService(uow_factory, projects)
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
        invite=InviteService(uow_factory, registry=registry),
        leader_chat=leader_chat,
        liveness=liveness,
        liveness_watchdog=liveness_watchdog,
        orchestrator=orchestrator,
        push_reasons=push_reasons,
        stall_watchdog=stall_watchdog,
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
        ),
        task_logs=TaskLogService(uow_factory),
        threads=ThreadService(uow_factory, wake_engine),
        artifacts=ArtifactService(uow_factory, store),
        artifact_store=store,
        runs=RunQueryService(uow_factory),
        auth=AuthService(uow_factory, workspaces, jwt_service, password_service),
        skills=skills,
        jwt_service=jwt_service,
        uow_factory=uow_factory,
    )
