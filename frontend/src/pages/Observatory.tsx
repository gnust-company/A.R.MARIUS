import { useEffect, useRef, useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router';
import { useTranslation } from 'react-i18next';
import type { TFunction } from 'i18next';
import { AnimatePresence } from 'framer-motion';
import {
  ArrowUpRight,
  Box,
  Inbox,
  MapPin,
  Maximize2,
  Minus,
  Moon,
  Plus,
  RotateCw,
  ScanLine,
  Sun,
  UserRound,
  UserPlus,
  Users,
} from 'lucide-react';
import PageTitle from '@/components/PageTitle';
import StatusChip from '@/components/StatusChip';
import AgentAvatar from '@/components/AgentAvatar';
import ObservatoryScene, { type ObservatoryHandle } from '@/components/observatory/ObservatoryScene';
import PortalModal from '@/components/observatory/PortalModal';
import type { SceneLabels, SceneState } from '@/components/observatory/OfficeEngine';
import {
  ZONES,
  layoutOffice,
  normalizeTaskStatus,
  openTasksOf,
  podLetter,
  type AgentZone,
  type Assignment,
} from '@/components/observatory/officePlan';
import { useTheme } from '@/hooks/use-theme';
import { useViewport } from '@/hooks/use-viewport';
import { cn, wsHref } from '@/lib/utils';
import { agentsOf } from '@/lib/workspaceScope';
import { useAppStore, type Marius, type Task } from '@/store/appStore';

/*
 * Đài quan sát — the workspace as one office floor (DESIGN §5–§9). Live data only: the agents
 * of this workspace and the tasks of its projects, seated by `layoutOffice`. The prototype's
 * two mock workspaces are deliberately not here; nothing on this screen is invented.
 */

const STATUS_DOT: Record<string, string> = {
  working: 'bg-gold',
  online: 'bg-success',
  idle: 'bg-success',
  hung: 'bg-danger',
  offline: 'bg-ink-faint',
};

const overlay = 'border border-line bg-surface/85 text-ink backdrop-blur-md';

function relativeTime(iso: string | null | undefined, t: TFunction): string {
  if (!iso) return t('common.never');
  const minutes = Math.floor((Date.now() - new Date(iso).getTime()) / 60000);
  if (minutes < 1) return t('common.justNow');
  if (minutes < 60) return t('common.minutesAgo', { count: minutes });
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return t('common.hoursAgo', { count: hours });
  return t('common.daysAgo', { count: Math.floor(hours / 24) });
}

function assignmentText(assignment: Assignment | undefined, t: TFunction): string {
  if (!assignment) return '';
  switch (assignment.kind) {
    case 'desk':
      return t('observatory.assignment.desk', { pod: podLetter(assignment.pod), desk: assignment.desk });
    case 'bed':
      return t('observatory.assignment.bed', { bed: assignment.bed });
    case 'clinicQueue':
      return t('observatory.assignment.clinicQueue', { position: assignment.position });
    case 'presenting':
      return t('observatory.assignment.presenting');
    case 'ceoQueue':
      return t('observatory.assignment.ceoQueue', { position: assignment.position });
    case 'loungeSeat':
      return t('observatory.assignment.loungeSeat', { seat: assignment.seat });
    case 'loungeFloor':
      return t('observatory.assignment.loungeFloor');
    case 'checkIn':
      return t('observatory.assignment.checkIn', { position: assignment.position });
  }
}

function agentName(agent: Marius): string {
  return agent.displayName || agent.name;
}

function runtimeLabel(agent: Marius): string {
  return agent.runtime?.cli_kind ?? agent.adapterType ?? '';
}

export default function Observatory() {
  const { workspaceId } = useParams<{ workspaceId: string }>();
  // Keyed by workspace: switching resets selection and camera, and rebuilds the one scene.
  return <ObservatoryView key={workspaceId} workspaceId={workspaceId ?? ''} />;
}

function ObservatoryView({ workspaceId }: { workspaceId: string }) {
  const { t, i18n } = useTranslation();
  const navigate = useNavigate();
  const viewport = useViewport();
  const [theme] = useTheme();
  const scene = useRef<ObservatoryHandle>(null);

  const allProjects = useAppStore((s) => s.projects);
  const allMariuses = useAppStore((s) => s.mariuses);
  const allTasks = useAppStore((s) => s.tasks);
  const workspaces = useAppStore((s) => s.workspaces);
  const hydrateProject = useAppStore((s) => s.hydrateProject);
  const sseConnected = useAppStore((s) => s.sseConnected);
  const inboxPending = useAppStore((s) => s.inboxPending);

  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [detailId, setDetailId] = useState<string | null>(null);
  const [activeZone, setActiveZone] = useState<AgentZone | null>(null);
  const [activePod, setActivePod] = useState<number | null>(null);

  const projects = allProjects.filter((p) => p.workspaceId === workspaceId);
  const projectIds = new Set(projects.map((p) => p.id));
  const tasks = allTasks.filter((task) => projectIds.has(task.projectId));
  const agents = agentsOf(allMariuses, workspaceId);
  const workspaceName = workspaces.find((w) => w.id === workspaceId)?.name ?? '';

  // The workspace slice carries projects but not their tasks; load each project's tasks so
  // the floor can seat agents by what they hold.
  const projectKey = projects.map((p) => p.id).join(',');
  useEffect(() => {
    projectKey
      .split(',')
      .filter(Boolean)
      .forEach((id) => void hydrateProject(id).catch(() => {}));
  }, [projectKey, hydrateProject]);

  const layout = layoutOffice(agents, tasks);
  const { plan } = layout;
  const zoneOfAgent = (id: string): AgentZone => layout.zones.get(id) ?? 'lounge';
  const zoneCount = (zone: AgentZone) => agents.filter((agent) => zoneOfAgent(agent.id) === zone).length;
  const running = agents.filter(
    (agent) => agent.status === 'working' || openTasksOf(agent.id, tasks).some((task) => normalizeTaskStatus(task.status) === 'in_progress')
  ).length;
  const blocked = tasks.filter((task) => normalizeTaskStatus(task.status) === 'blocked').length;

  const sceneState: SceneState = {
    agents: agents.map((agent) => ({ id: agent.id, name: agentName(agent), status: agent.status, runtimeLabel: runtimeLabel(agent) })),
    layout,
    theme,
    selectedId,
  };
  const sceneLabels: SceneLabels = {
    canvas: t('observatory.canvas'),
    mainCirculation: t('observatory.sign.mainCirculation'),
    entry: t('observatory.sign.entry'),
    reception: [t('observatory.sign.receptionTitle'), t('observatory.sign.receptionSub')],
    lounge: [t('observatory.sign.loungeTitle'), t('observatory.sign.loungeSub')],
    pod: (letter) => [t('observatory.sign.podTitle', { letter }), t('observatory.sign.podSub')],
    podFloor: (letter) => t('observatory.sign.podFloor', { letter }),
    clinic: (beds, waiting) => [t('observatory.sign.clinicTitle'), t('observatory.sign.clinicSub', { beds, waiting })],
    patron: (queue) => [t('observatory.sign.patronTitle'), t('observatory.sign.patronSub', { queue })],
    approvalQueue: t('observatory.sign.approvalQueue'),
  };
  // The scene is rebuilt only when the building itself changes shape (or its signs' words).
  const sceneKey = [plan.workPods, plan.clinicBeds, plan.clinicWaiting, plan.large, plan.reviewCount, i18n.language].join(':');

  const inboxHref = wsHref(workspaceId, '/inbox');
  const openPatron = () => navigate(inboxHref);
  const inspect = (id: string) => {
    setSelectedId(id);
    setDetailId(id);
  };
  const pickFromList = (id: string) => {
    setActiveZone(null);
    setActivePod(null);
    scene.current?.focusAgent(id);
    inspect(id);
  };
  const focusZone = (zone: AgentZone) => {
    setActiveZone(zone);
    setActivePod(null);
    scene.current?.focusZone(zone);
  };
  const focusPod = (index: number | null) => {
    setActivePod(index);
    setActiveZone(index === null ? null : 'work');
    if (index === null) scene.current?.reset();
    else scene.current?.focusWorkPod(index);
  };
  const resetCamera = () => {
    setActiveZone(null);
    setActivePod(null);
    scene.current?.reset();
  };
  const camera = (action: 'zoomOut' | 'zoomIn' | 'rotate' | 'reset') => {
    if (action === 'zoomOut') scene.current?.zoom(-1);
    if (action === 'zoomIn') scene.current?.zoom(1);
    if (action === 'rotate') scene.current?.rotate();
    if (action === 'reset') resetCamera();
  };

  const statusLabel = (status: string) => t(`directory.status.${status}`);
  const zoneLabel = (zone: AgentZone) => t(`observatory.zone.${zone}`);
  const detail = agents.find((agent) => agent.id === detailId);
  const pickWithSelect = viewport === 'phone' || agents.length > 8;

  const renderHover = (id: string) => {
    const agent = agents.find((item) => item.id === id);
    if (!agent) return null;
    return (
      <div>
        <div className="flex items-center gap-[7px]">
          <span className={cn('status-dot', STATUS_DOT[agent.status])} />
          <strong className="min-w-0 truncate font-display text-[20px] font-normal text-ink-strong">{agentName(agent)}</strong>
          <small className="ml-auto shrink-0 text-[10px] text-ink-light">{statusLabel(agent.status)}</small>
        </div>
        {agent.role && <p className="mb-2 mt-1 truncate text-[11px] text-ink-light">{agent.role}</p>}
        <span className="mt-2 block border-t border-line pt-2 text-[11px] font-semibold text-sapphire-strong">{zoneLabel(zoneOfAgent(id))}</span>
        <small className="mt-1 block text-[10px] text-ink-light">{assignmentText(layout.placements.get(id)?.assignment, t)}</small>
      </div>
    );
  };

  return (
    <div className="mx-auto flex w-full max-w-[1480px] flex-col gap-3 pb-10">
      <PageTitle
        eyebrow={t('observatory.eyebrow')}
        title={t('nav.observatory')}
        subtitle={t('observatory.subtitle')}
        actions={
          <div className="flex flex-wrap items-center gap-x-[18px] gap-y-1 pb-1 text-[12px] text-ink-light">
            <span className="flex items-center gap-2">
              <span className="status-dot bg-gold" />
              {t('observatory.running', { count: running })}
            </span>
            <span className="flex items-center gap-2">
              <span className="status-dot bg-danger" />
              {t('observatory.blocked', { count: blocked })}
            </span>
          </div>
        }
      />

      {/* Capacity strip: the floor's resources, outside the scene (DESIGN §9). */}
      <div aria-label={t('observatory.capacity.label')} className="no-scrollbar mt-4 flex items-center gap-[7px] overflow-x-auto md:flex-wrap">
        {[
          { icon: Users, value: agents.length, label: t('observatory.capacity.agents') },
          { value: plan.workPods, label: t('observatory.capacity.pods') },
          { value: `${plan.workCount}/${plan.workCapacity}`, label: t('observatory.capacity.desks') },
          { value: `${Math.min(plan.clinicCount, plan.clinicBeds)}/${plan.clinicBeds}`, label: t('observatory.capacity.beds') },
          { value: Math.max(0, plan.reviewCount - 1), label: t('observatory.capacity.ceoQueue') },
        ].map(({ icon: Icon, value, label }) => (
          <span key={label} className="inline-flex min-h-[30px] shrink-0 items-center gap-[5px] rounded-md border border-line bg-surface/80 px-2.5 py-1.5 text-[11px] text-ink-light">
            {Icon && <Icon className="h-4 w-4 text-sapphire-strong" aria-hidden />}
            <strong className="font-mono font-medium text-ink">{value}</strong>
            {label}
          </span>
        ))}
        {plan.clinicWaiting > 0 && (
          <span className="inline-flex min-h-[30px] shrink-0 items-center rounded-md border border-gold/35 bg-gold-soft px-2.5 py-1.5 text-[11px] font-semibold text-gold">
            {t('observatory.capacity.clinicWaiting', { count: plan.clinicWaiting })}
          </span>
        )}
      </div>

      {plan.workPods > 1 && (
        <div aria-label={t('observatory.podNav.label')} role="group" className="no-scrollbar flex items-center gap-[5px] overflow-x-auto rounded-[9px] border border-line bg-surface p-[5px]">
          <span className="hidden shrink-0 px-2.5 font-mono text-[9px] uppercase tracking-[0.06em] text-ink-muted md:inline">{t('observatory.podNav.label')}</span>
          {[null, ...plan.workCenters.map((_, index) => index)].map((index) => {
            const active = activePod === index;
            return (
              <button
                key={index ?? 'all'}
                type="button"
                aria-pressed={active}
                onClick={() => focusPod(index)}
                className={cn(
                  'min-h-[31px] shrink-0 rounded-md px-3 py-1.5 text-[11px] transition-colors',
                  active ? 'bg-sapphire-soft font-semibold text-sapphire-strong' : 'text-ink-light hover:bg-surface-hover hover:text-ink'
                )}
              >
                {index === null ? t('observatory.podNav.overview') : t('observatory.podNav.pod', { letter: podLetter(index) })}
              </button>
            );
          })}
        </div>
      )}

      <section
        aria-label={t('observatory.sceneLabel')}
        className={cn(
          'relative min-w-0 overflow-hidden rounded-xl border border-line-strong bg-canvas-deep shadow-gilt',
          plan.large ? 'h-[520px] md:h-[680px] xl:h-[720px]' : 'h-[600px] md:h-[680px] xl:h-[720px]'
        )}
      >
        <ObservatoryScene
          key={sceneKey}
          ref={scene}
          state={sceneState}
          labels={sceneLabels}
          onSelect={inspect}
          onOpenPatron={openPatron}
          renderHover={renderHover}
        />

        {/* Time of day follows the theme: lamps on at night, off by day (DESIGN §4). */}
        <div className={cn('pointer-events-none absolute left-3 right-[70px] top-3 z-[2] flex items-center gap-2.5 rounded-md px-3 py-2.5 md:left-[18px] md:right-auto md:top-[18px]', overlay)}>
          <span className="text-gold">{theme === 'light' ? <Sun className="h-[18px] w-[18px]" aria-hidden /> : <Moon className="h-[18px] w-[18px]" aria-hidden />}</span>
          <div className="min-w-0">
            <strong className="block truncate text-[11px] font-semibold">{t(theme === 'light' ? 'observatory.time.dayTitle' : 'observatory.time.nightTitle')}</strong>
            <small className="mt-0.5 block truncate text-[10px] text-ink-light">{t(theme === 'light' ? 'observatory.time.dayBody' : 'observatory.time.nightBody')}</small>
          </div>
        </div>

        {/* Zone navigation and the way into the Patron inbox, stacked top-right. */}
        <div className="absolute right-2.5 top-[76px] z-[3] flex w-12 flex-col gap-2 md:right-[18px] md:top-[18px] md:w-[174px] xl:w-[190px]">
          <nav aria-label={t('observatory.zoneNav.label')} className={cn('grid rounded-[10px] p-1 md:p-[5px]', overlay)}>
            {ZONES.map((zone, index) => {
              const active = activeZone === zone && activePod === null;
              const title = zoneLabel(zone);
              return (
                <button
                  key={zone}
                  type="button"
                  onClick={() => focusZone(zone)}
                  aria-pressed={active}
                  aria-label={t('observatory.zoneNav.focus', { zone: title })}
                  title={t('observatory.zoneNav.focus', { zone: title })}
                  className={cn(
                    'grid min-h-[34px] place-items-center border-b border-line px-1 py-1.5 text-center transition-colors hover:bg-surface-hover md:min-h-[39px] md:grid-cols-[27px_1fr] md:place-items-stretch md:items-center md:gap-2 md:px-2 md:text-left',
                    active && 'bg-sapphire-soft'
                  )}
                >
                  <span className="font-mono text-[10px] text-gold">0{index + 1}</span>
                  <span className="hidden min-w-0 md:block">
                    <strong className="block truncate text-[11px] font-semibold text-ink-strong">{title}</strong>
                    <small className="block text-[10px] text-ink-light">{t('observatory.zoneNav.count', { count: zoneCount(zone) })}</small>
                  </span>
                </button>
              );
            })}
            <button type="button" onClick={resetCamera} className="min-h-[32px] text-[10px] text-ink-light transition-colors hover:text-ink-strong">
              <span className="font-mono uppercase md:hidden">{t('observatory.zoneNav.overviewShort')}</span>
              <span className="hidden md:inline">{t('observatory.zoneNav.overview')}</span>
            </button>
          </nav>
          <Link
            to={inboxHref}
            aria-label={t('observatory.patronEntry.detail', { count: inboxPending })}
            className={cn(
              'flex min-h-[45px] items-center justify-center gap-2.5 rounded-[9px] border-gold/45 p-2 transition-colors hover:border-gold hover:bg-surface-hover md:min-h-[52px] md:justify-start md:px-2.5',
              overlay,
              'border-gold/45'
            )}
          >
            <Inbox className="h-[19px] w-[19px] shrink-0 text-gold" aria-hidden />
            <span className="hidden min-w-0 md:block">
              <strong className="block text-[11px] text-ink-strong">{t('observatory.patronEntry.title')}</strong>
              <small className="block text-[10px] leading-snug text-ink-light">{t('observatory.patronEntry.detail', { count: inboxPending })}</small>
            </span>
            <ArrowUpRight className="ml-auto hidden h-4 w-4 shrink-0 text-ink-light md:block" aria-hidden />
          </Link>
        </div>

        {/* Camera: every button drives the real camera. */}
        <div role="group" aria-label={t('observatory.camera.label')} className={cn('absolute bottom-[78px] left-3 z-[3] flex items-center rounded-[9px] p-1 md:bottom-[88px] md:left-[18px]', overlay)}>
          {(
            [
              { action: 'zoomOut', icon: Minus },
              { action: 'zoomIn', icon: Plus },
              { action: 'rotate', icon: RotateCw },
              { action: 'reset', icon: Maximize2 },
            ] as const
          ).map(({ action, icon: Icon }, index) => {
            const label = t(`observatory.camera.${action}`);
            return (
            <span key={label} className="flex items-center">
              {index === 2 && <span className="mx-1 h-5 w-px bg-line" />}
              <button
                type="button"
                onClick={() => camera(action)}
                aria-label={label}
                title={label}
                className="grid h-10 w-10 place-items-center rounded-md text-ink-light transition-colors hover:bg-surface-hover hover:text-sapphire-strong"
              >
                <Icon className="h-[18px] w-[18px]" aria-hidden />
              </button>
            </span>
            );
          })}
        </div>

        <div className={cn('pointer-events-none absolute bottom-[96px] right-[18px] z-[2] hidden max-w-[330px] items-center gap-[7px] rounded-md px-2.5 py-1.5 text-[11px] text-ink-light lg:flex', overlay)}>
          <Box className="h-[15px] w-[15px] shrink-0" aria-hidden />
          {t('observatory.gesture')}
        </div>

        {/* Agent picker: avatars while they fit, a select on a phone or a crowded floor. */}
        <div aria-label={t('observatory.dock.label')} role="group" className={cn('absolute inset-x-2.5 bottom-2.5 z-[3] flex justify-center gap-1 rounded-xl p-[5px] md:inset-x-[14px] md:bottom-[14px]', overlay)}>
          {agents.length === 0 ? null : pickWithSelect ? (
            <label className="grid w-full grid-cols-1 items-center gap-1 px-1 md:grid-cols-[auto_minmax(220px,340px)] md:justify-center md:gap-3.5">
              <span className="px-1 text-[10px] text-ink-light">{t('observatory.dock.select', { count: agents.length })}</span>
              <select
                className="field min-h-[38px] py-1.5 text-[12px]"
                value={selectedId ?? ''}
                onChange={(event) => event.target.value && pickFromList(event.target.value)}
              >
                <option value="" disabled>
                  {t('observatory.dock.placeholder')}
                </option>
                {[...agents]
                  .sort((a, b) => agentName(a).localeCompare(agentName(b)))
                  .map((agent) => (
                    <option key={agent.id} value={agent.id}>
                      {agentName(agent)} · {zoneLabel(zoneOfAgent(agent.id))}
                    </option>
                  ))}
              </select>
            </label>
          ) : (
            agents.map((agent) => {
              const active = agent.id === selectedId;
              return (
                <button
                  key={agent.id}
                  type="button"
                  onClick={() => pickFromList(agent.id)}
                  aria-pressed={active}
                  className={cn(
                    'flex min-h-[48px] min-w-[86px] items-center justify-center gap-[7px] rounded-lg px-2.5 py-1 text-[12px] transition-colors',
                    active ? 'bg-sapphire-soft text-ink-strong ring-1 ring-inset ring-sapphire/45' : 'text-ink-light hover:bg-surface-hover hover:text-ink-strong'
                  )}
                >
                  <AgentAvatar name={agentName(agent)} status={agent.status} size="sm" />
                  <span className="max-w-[110px] truncate">{agentName(agent)}</span>
                </button>
              );
            })
          )}
        </div>

        {agents.length === 0 && (
          <div className="absolute inset-0 z-[4] grid place-items-center px-5">
            <div className={cn('flex max-w-[380px] flex-col items-center rounded-xl px-6 py-8 text-center shadow-gilt', overlay)}>
              <span className="mb-4 grid h-14 w-14 place-items-center rounded-full border border-line bg-canvas-deep text-ink-muted">
                <UserRound className="h-6 w-6" strokeWidth={1.5} aria-hidden />
              </span>
              <h2 className="font-display text-display-sm text-ink-strong">{t('observatory.empty.title')}</h2>
              <p className="mb-6 mt-2 text-body-md text-ink-light">{t('observatory.empty.body')}</p>
              <Link to={wsHref(workspaceId, '/agents')} className="btn btn-primary">
                <UserPlus className="h-4 w-4" aria-hidden />
                {t('observatory.empty.action')}
              </Link>
            </div>
          </div>
        )}
      </section>

      {/* Coordination strip: what the scene is showing and how fresh it is. */}
      <div className="flex flex-col gap-4 rounded-lg border border-line bg-surface/75 px-5 py-4 md:flex-row md:items-center md:gap-7">
        <div className="md:min-w-[235px]">
          <span className="eyebrow">{t('observatory.strip.eyebrow')}</span>
          <strong className="mt-1 block font-display text-[16px] font-normal text-ink-strong">{t('observatory.strip.title')}</strong>
        </div>
        <dl className="grid flex-1 grid-cols-2 gap-x-8 gap-y-3 sm:flex sm:gap-8">
          <div className="min-w-0">
            <dt className="text-[10px] text-ink-muted">{t('observatory.strip.data')}</dt>
            <dd className="mt-0.5 truncate text-[12px] text-ink">{workspaceName}</dd>
          </div>
          <div>
            <dt className="text-[10px] text-ink-muted">{t('observatory.strip.modules')}</dt>
            <dd className="mt-0.5 text-[12px] text-ink">{t('observatory.strip.modulesValue', { count: plan.workPods })}</dd>
          </div>
          <div>
            <dt className="text-[10px] text-ink-muted">{t('observatory.strip.waiting')}</dt>
            <dd className="mt-0.5 text-[12px] text-ink">{t('observatory.strip.waitingValue', { count: plan.clinicWaiting + Math.max(0, plan.reviewCount - 1) })}</dd>
          </div>
        </dl>
        <span className={cn('flex items-center gap-2 font-mono text-[10px] uppercase tracking-[0.12em]', sseConnected ? 'text-success' : 'text-gold')}>
          <span className={cn('h-[7px] w-[7px] rounded-full', sseConnected ? 'bg-success' : 'bg-gold')} />
          {t(sseConnected ? 'observatory.strip.live' : 'observatory.strip.reconnecting')}
        </span>
      </div>

      <AnimatePresence>
        {detail && (
          <AgentObservation
            key={detail.id}
            agent={detail}
            zone={zoneOfAgent(detail.id)}
            assignment={assignmentText(layout.placements.get(detail.id)?.assignment, t)}
            tasks={openTasksOf(detail.id, tasks)}
            projects={projects}
            workspaceId={workspaceId}
            onClose={() => setDetailId(null)}
          />
        )}
      </AnimatePresence>
    </div>
  );
}

function AgentObservation({
  agent,
  zone,
  assignment,
  tasks,
  projects,
  workspaceId,
  onClose,
}: {
  agent: Marius;
  zone: AgentZone;
  assignment: string;
  tasks: Task[];
  projects: { id: string; key?: string; name: string }[];
  workspaceId: string;
  onClose: () => void;
}) {
  const { t, i18n } = useTranslation();
  const runtime = runtimeLabel(agent);
  const description =
    zone === 'clinic'
      ? agent.lastSeen
        ? t('observatory.zoneDescription.clinic', { lastSeen: relativeTime(agent.lastSeen, t) })
        : t('observatory.zoneDescription.clinicNever')
      : t(`observatory.zoneDescription.${zone}`);
  const label = 'font-mono text-[10px] uppercase tracking-[0.08em] text-ink-muted';

  return (
    <PortalModal
      title={agentName(agent)}
      eyebrow={t('observatory.modal.eyebrow', { runtime: (runtime || t('observatory.modal.notPlaced')).toUpperCase() })}
      onClose={onClose}
    >
      <div className="flex items-start gap-4 sm:items-center">
        <AgentAvatar name={agentName(agent)} status={agent.status} size="lg" />
        <div className="min-w-0">
          <StatusChip status={agent.status} label={t(`directory.status.${agent.status}`)} />
          {agent.role && <p className="mt-2 text-[14px] text-ink">{agent.role}</p>}
          {agent.description && <small className="mt-1 block text-[12px] leading-relaxed text-ink-light">{agent.description}</small>}
        </div>
      </div>

      <div className="my-5">
        <Link to={wsHref(workspaceId, `/agents/${agent.id}`)} className="btn btn-secondary w-full sm:w-auto">
          <UserRound className="h-[17px] w-[17px]" aria-hidden />
          {t('observatory.modal.profile')}
        </Link>
      </div>

      <section className={cn('rounded-lg border border-line p-[18px]', zone === 'patron' ? 'bg-gold-soft/60' : 'bg-canvas-deep')}>
        <div className={cn('flex items-center justify-between', label, 'text-sapphire-strong')}>
          <span>{t('observatory.modal.location')}</span>
          <MapPin className="h-4 w-4" aria-hidden />
        </div>
        <h3 className="mb-1 mt-2.5 font-display text-[23px] font-normal text-ink-strong">{t(`observatory.zone.${zone}`)}</h3>
        <strong className="mb-2.5 mt-0.5 inline-flex rounded-[5px] bg-sapphire/10 px-2 py-1 font-mono text-[11px] font-medium leading-normal text-sapphire-strong">
          {assignment}
        </strong>
        <p className="text-[13px] leading-relaxed text-ink-light">{description}</p>
      </section>

      <section className="border-b border-line py-5">
        <div className={cn('flex items-center justify-between', label)}>
          <span>{t('observatory.modal.tasks', { count: tasks.length })}</span>
          <ScanLine className="h-4 w-4" aria-hidden />
        </div>
        {tasks.length ? (
          <div className="mt-3 grid gap-2.5">
            {tasks.map((task) => {
              const status = normalizeTaskStatus(task.status);
              const counts = task.cardCounts;
              const project = projects.find((p) => p.id === task.projectId);
              const due = task.dueDate ? new Date(task.dueDate).toLocaleDateString(i18n.language) : null;
              return (
                <Link
                  key={task.id}
                  to={wsHref(workspaceId, `/tasks/${task.id}`)}
                  className="group block rounded-[10px] border border-line bg-surface px-4 py-3.5 transition-colors hover:border-sapphire/50 hover:bg-surface-hover"
                >
                  <span className="flex items-center gap-2.5">
                    <span className="task-code">{task.identifier ?? project?.key ?? ''}</span>
                    <StatusChip status={status} label={t(`tasks.status.${status}`)} />
                    <ArrowUpRight className="ml-auto h-4 w-4 text-ink-muted transition-colors group-hover:text-sapphire-strong" aria-hidden />
                  </span>
                  <strong className="mb-1.5 mt-2 block font-display text-[17px] font-normal leading-snug text-ink-strong">{task.title}</strong>
                  <span className="block text-[11px] text-ink-muted">
                    {[project?.name, due && t('observatory.modal.due', { date: due }), counts?.criteriaTotal ? t('observatory.modal.criteria', { done: counts.criteriaPassed, total: counts.criteriaTotal }) : null]
                      .filter(Boolean)
                      .join(' · ')}
                  </span>
                  {counts?.criteriaTotal ? (
                    <span className="mt-2.5 block h-1 overflow-hidden rounded-full bg-canvas-deep">
                      <span className="block h-full rounded-full bg-sapphire" style={{ width: `${(counts.criteriaPassed / counts.criteriaTotal) * 100}%` }} />
                    </span>
                  ) : null}
                  {status === 'blocked' && task.statusReason && <small className="mt-2.5 block text-[12px] leading-normal text-danger">{task.statusReason}</small>}
                </Link>
              );
            })}
          </div>
        ) : (
          <div className="mt-3 rounded-[9px] border border-dashed border-line-strong p-4">
            <strong className="text-[13px] text-ink">{t('observatory.modal.noTask')}</strong>
            <p className="mt-1 text-[12px] text-ink-light">{t(zone === 'clinic' ? 'observatory.modal.noTaskClinic' : 'observatory.modal.noTaskReady')}</p>
          </div>
        )}
      </section>

      <section className="grid grid-cols-2 gap-x-5 gap-y-4 border-b border-line py-5">
        {[
          [t('observatory.modal.runtime'), agent.runtime?.cli_kind ?? t('observatory.modal.notPlaced')],
          [t('observatory.modal.machine'), agent.runtime?.machine_name ?? t('observatory.modal.notPlaced')],
          [t('observatory.modal.adapter'), agent.adapterType ?? '—'],
          [t('observatory.modal.lastSeen'), relativeTime(agent.lastSeen, t)],
        ].map(([name, value]) => (
          <div key={name} className="min-w-0">
            <span className={cn('block', label)}>{name}</span>
            <strong className="mt-1 block truncate text-[12px] font-medium text-ink">{value}</strong>
          </div>
        ))}
      </section>

      <section className="pt-5">
        <span className={cn('block', label)}>{t('observatory.modal.skills')}</span>
        <div className="mt-3 flex flex-wrap gap-1.5">
          {agent.skills?.length ? agent.skills.map((skill) => <span key={skill} className="chip">{skill}</span>) : <span className="chip">{t('observatory.modal.noSkills')}</span>}
        </div>
      </section>
    </PortalModal>
  );
}
