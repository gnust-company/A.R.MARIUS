import { useEffect, useMemo, useState, type ReactNode } from 'react';
import { Link, useParams } from 'react-router';
import { useTranslation } from 'react-i18next';
import type { TFunction } from 'i18next';
import { ArrowRight, Bell, CheckCircle2, Lock, Plus, Telescope, Zap, type LucideIcon } from 'lucide-react';
import PageTitle from '@/components/PageTitle';
import StatusChip from '@/components/StatusChip';
import AgentAvatar from '@/components/AgentAvatar';
import { kindIcon, kindTone } from '@/components/inbox/inbox-utils';
import { getInbox, type InboxItemDTO } from '@/lib/api';
import { subscribeProjectEvents } from '@/lib/sse';
import { cn, wsHref } from '@/lib/utils';
import { useAppStore, type Marius, type Task } from '@/store/appStore';

/** The board's eleven spellings of a status, folded to the backend's eight. */
function normalizeStatus(status: string): string {
  const s = status.replace(/-/g, '_');
  if (s === 'review') return 'in_review';
  if (s === 'pending') return 'todo';
  return s;
}

const CLOSED_STATUSES = new Set(['done', 'cancelled']);

/** Which of an agent's tasks says most about what it is doing now — running beats waiting. */
const HOLDING_ORDER = ['in_progress', 'in_review', 'blocked', 'todo'];

/** Working first, then whoever is alive, then the rest. */
const PRESENCE_ORDER: Record<string, number> = { working: 0, online: 1, idle: 2, offline: 3 };

/** One meaning per colour (DESIGN §3.3), for the timeline's dots. */
const STATUS_DOT: Record<string, string> = {
  in_progress: 'bg-gold',
  in_review: 'bg-sapphire',
  blocked: 'bg-danger',
  done: 'bg-success',
};

/** Coalescing window for re-reading a project after a burst of its events, in ms. */
const REFRESH_DEBOUNCE_MS = 300;

/** How many waiting letters the front page lists before pointing at the inbox. */
const WAITING_SHOWN = 4;

function relativeTime(iso: string | null | undefined, t: TFunction): string {
  if (!iso) return '';
  const minutes = Math.floor((Date.now() - new Date(iso).getTime()) / 60000);
  if (minutes < 1) return t('common.justNow');
  if (minutes < 60) return t('common.minutesAgo', { count: minutes });
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return t('common.hoursAgo', { count: hours });
  return t('common.daysAgo', { count: Math.floor(hours / 24) });
}

function greetingKey(): string {
  const hour = new Date().getHours();
  if (hour < 12) return 'home.helloMorning';
  if (hour < 18) return 'home.helloAfternoon';
  return 'home.helloEvening';
}

/** Eyebrow, Lora title and an optional action on the right — the head of every panel here. */
function SectionHeader({ eyebrow, title, children }: { eyebrow: string; title: string; children?: ReactNode }) {
  return (
    <header className="flex flex-wrap items-center justify-between gap-x-4 gap-y-2">
      <div className="min-w-0">
        <p className="eyebrow">{eyebrow}</p>
        <h2 className="mt-1 font-display text-[22px] font-normal leading-tight tracking-[-0.015em] text-ink-strong sm:text-[24px]">
          {title}
        </h2>
      </div>
      {children && <div className="flex flex-wrap items-center gap-x-3 gap-y-1">{children}</div>}
    </header>
  );
}

/** One cell of the summary band: an icon, a large number, what it counts, and where it leads. */
function Metric({
  icon: Icon,
  value,
  label,
  detail,
  to,
}: {
  icon: LucideIcon;
  value: number;
  label: string;
  detail?: string;
  to?: string;
}) {
  const body = (
    <>
      <Icon className="h-[21px] w-[21px] shrink-0 text-gold" aria-hidden />
      <div className="min-w-0">
        <strong className="block font-display text-[30px] font-normal leading-none text-ink-strong">{value}</strong>
        <span className="mt-1 block font-body text-body-sm text-ink-light">{label}</span>
        {detail && <span className="block font-body text-body-xs text-ink-muted">{detail}</span>}
      </div>
      {to && <ArrowRight className="ml-auto h-[18px] w-[18px] shrink-0 text-ink-faint" aria-hidden />}
    </>
  );
  const cls = 'flex min-h-[88px] min-w-0 items-center gap-3.5 px-5 py-4';
  return to ? (
    <Link to={to} className={cn(cls, 'transition-colors hover:bg-surface-hover')}>
      {body}
    </Link>
  ) : (
    <div className={cls}>{body}</div>
  );
}

/**
 * The workspace's front page: what is waiting on the patron, what each agent is doing, how
 * each project stands. Everything else in the workspace is one click from here.
 */
export default function Home() {
  const { t, i18n } = useTranslation();
  const { workspaceId } = useParams<{ workspaceId: string }>();
  const allProjects = useAppStore((s) => s.projects);
  const allMariuses = useAppStore((s) => s.mariuses);
  const allTasks = useAppStore((s) => s.tasks);
  const hydrateProject = useAppStore((s) => s.hydrateProject);
  // Kept true by the one inbox stream under Layout; a change is the signal to re-read.
  const inboxSignal = useAppStore((s) => s.inboxPending);
  const [inbox, setInbox] = useState<InboxItemDTO[]>([]);
  const [streamDown, setStreamDown] = useState(false);

  const projects = useMemo(
    () => allProjects.filter((p) => p.workspaceId === workspaceId),
    [allProjects, workspaceId]
  );
  const mariuses = useMemo(
    () => allMariuses.filter((m) => m.workspaceId === workspaceId),
    [allMariuses, workspaceId]
  );
  const projectIds = useMemo(() => new Set(projects.map((p) => p.id)), [projects]);
  const tasks = useMemo(() => allTasks.filter((tk) => projectIds.has(tk.projectId)), [allTasks, projectIds]);

  // The workspace slice carries projects but not their tasks; the board loads those per
  // project, so the front page asks for each project it is about to summarise.
  const projectKey = projects.map((p) => p.id).join(',');
  useEffect(() => {
    projects.forEach((p) => void hydrateProject(p.id).catch(() => {}));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [projectKey, hydrateProject]);

  // Keep the timeline moving: each open project's channel says when one of its tasks moved,
  // and that is the signal to re-read that project — never state built from the event
  // (contracts/push-events, principle 1). Closed projects do not move, so they are not watched.
  const liveKey = projects
    .filter((p) => p.status !== 'closed')
    .map((p) => p.id)
    .join(',');
  useEffect(() => {
    const ids = liveKey.split(',').filter(Boolean);
    const timers = new Map<string, ReturnType<typeof setTimeout>>();
    const offs = ids.map((id) =>
      subscribeProjectEvents(
        id,
        () => {
          setStreamDown(false);
          if (timers.has(id)) return;
          timers.set(
            id,
            setTimeout(() => {
              timers.delete(id);
              void hydrateProject(id).catch(() => {});
            }, REFRESH_DEBOUNCE_MS)
          );
        },
        () => setStreamDown(true)
      )
    );
    return () => {
      timers.forEach((timer) => clearTimeout(timer));
      offs.forEach((off) => off());
    };
  }, [liveKey, hydrateProject]);

  useEffect(() => {
    let alive = true;
    getInbox({ status: 'pending' })
      .then((items) => {
        if (alive) setInbox(items.filter((i) => !i.workspace_id || i.workspace_id === workspaceId));
      })
      .catch(() => {});
    return () => {
      alive = false;
    };
  }, [workspaceId, inboxSignal]);

  const openTasks = tasks.filter((tk) => !CLOSED_STATUSES.has(normalizeStatus(tk.status)));
  const blocked = tasks
    .filter((tk) => normalizeStatus(tk.status) === 'blocked')
    .sort((a, b) => (b.updatedAt ?? b.createdAt).localeCompare(a.updatedAt ?? a.createdAt));
  const running = mariuses.filter((m) => m.status === 'working');
  const alive = mariuses.filter((m) => m.status !== 'offline');
  const activeProjects = projects.filter((p) => p.status !== 'closed');

  const agentRows = [...mariuses].sort(
    (a, b) => (PRESENCE_ORDER[a.status] ?? 9) - (PRESENCE_ORDER[b.status] ?? 9)
  );
  const holdingOf = (agent: Marius): Task | undefined => {
    const own = tasks.filter((tk) => tk.assigneeId === agent.id);
    for (const status of HOLDING_ORDER) {
      const hit = own.find((tk) => normalizeStatus(tk.status) === status);
      if (hit) return hit;
    }
    return undefined;
  };

  const recent = [...tasks]
    .sort((a, b) => (b.updatedAt ?? b.createdAt).localeCompare(a.updatedAt ?? a.createdAt))
    .slice(0, 6);
  const projectOf = (id?: string | null) => projects.find((p) => p.id === id);
  const taskOf = (id?: string | null) => (id ? tasks.find((tk) => tk.id === id) : undefined);

  const now = new Date();
  const locale = i18n.language === 'vi' ? 'vi-VN' : 'en-US';
  const dateEyebrow = `${now.toLocaleDateString(locale, { weekday: 'long' })} · ${now.toLocaleDateString(locale, {
    day: '2-digit',
    month: '2-digit',
    year: 'numeric',
  })}`;

  return (
    <div className="mx-auto flex w-full max-w-[1280px] min-w-0 flex-col gap-6 pb-10 sm:gap-7">
      <PageTitle
        eyebrow={dateEyebrow}
        title={t(greetingKey())}
        subtitle={t('home.lede')}
        actions={
          <Link to={wsHref(workspaceId, '/observatory')} className="btn btn-primary w-full md:w-auto">
            <Telescope className="h-[18px] w-[18px]" aria-hidden />
            {t('home.openObservatory')}
          </Link>
        }
      />

      <section
        aria-label={t('home.metricsLabel')}
        className="grid grid-cols-1 divide-y divide-line overflow-hidden rounded-lg border border-line bg-surface md:grid-cols-3 md:divide-x md:divide-y-0"
      >
        <Metric icon={Bell} value={inbox.length} label={t('home.metricWaiting')} to={wsHref(workspaceId, '/inbox')} />
        <Metric
          icon={Zap}
          value={running.length}
          label={t('home.metricRunning')}
          detail={t('home.metricRunningDetail', { alive: alive.length, total: mariuses.length })}
          to={wsHref(workspaceId, '/observatory')}
        />
        <Metric
          icon={Lock}
          value={blocked.length}
          label={t('home.metricBlocked')}
          detail={t('home.metricBlockedDetail', { open: openTasks.length })}
          // The most recently blocked task is the one to look at first.
          to={blocked[0] ? wsHref(workspaceId, `/tasks/${blocked[0].id}`) : undefined}
        />
      </section>

      <div className="grid min-w-0 grid-cols-1 items-start gap-5 xl:grid-cols-[minmax(0,1.5fr)_minmax(300px,0.8fr)]">
        <section className="surface min-w-0 p-5 sm:p-6">
          <SectionHeader eyebrow={t('home.inboxEyebrow')} title={t('home.inboxTitle')}>
            <Link to={wsHref(workspaceId, '/inbox')} className="btn-text">
              {t('home.openInbox')} <ArrowRight className="h-4 w-4" aria-hidden />
            </Link>
          </SectionHeader>
          {inbox.length === 0 ? (
            <p className="mt-4 flex items-center gap-2.5 border-t border-line pt-4 font-body text-body-md text-ink-light">
              <CheckCircle2 className="h-5 w-5 shrink-0 text-success" aria-hidden />
              {t('home.waitingEmpty')}
            </p>
          ) : (
            <div className="mt-4">
              {inbox.slice(0, WAITING_SHOWN).map((item) => {
                const Icon = kindIcon(item.kind);
                const project = projectOf(item.project_id);
                const code = taskOf(item.task_id)?.identifier;
                return (
                  <Link
                    key={item.id}
                    to={`${wsHref(workspaceId, '/inbox')}?item=${encodeURIComponent(item.id)}`}
                    className="group flex min-w-0 items-start gap-3.5 border-t border-line py-4"
                  >
                    <span
                      className={cn(
                        'grid h-[39px] w-[39px] shrink-0 place-items-center rounded-full border border-line',
                        kindTone(item)
                      )}
                      aria-hidden
                    >
                      <Icon className="h-[18px] w-[18px]" />
                    </span>
                    <div className="min-w-0 flex-1">
                      <span className="task-code block truncate">
                        {[project?.key ?? project?.name, code].filter(Boolean).join(' · ') ||
                          t(`inbox.kind.${item.kind}`, { defaultValue: item.kind })}
                      </span>
                      <strong className="mt-1 mb-1 block break-words font-display text-[18px] font-normal leading-snug text-ink-strong transition-colors group-hover:text-sapphire-strong">
                        {item.title}
                      </strong>
                      {item.body && (
                        <p className="line-clamp-2 break-words font-body text-body-sm leading-relaxed text-ink-light">
                          {item.body}
                        </p>
                      )}
                      <p className="mt-1 font-body text-body-xs text-ink-muted">
                        {[t(`inbox.kind.${item.kind}`, { defaultValue: item.kind }), relativeTime(item.created_at, t)]
                          .filter(Boolean)
                          .join(' · ')}
                      </p>
                    </div>
                    <ArrowRight className="mt-5 h-[18px] w-[18px] shrink-0 text-ink-faint" aria-hidden />
                  </Link>
                );
              })}
              {inbox.length > WAITING_SHOWN && (
                <Link
                  to={wsHref(workspaceId, '/inbox')}
                  className="btn-text w-full justify-center border-t border-line"
                >
                  {t('home.inboxMore', { count: inbox.length - WAITING_SHOWN })}
                </Link>
              )}
            </div>
          )}
        </section>

        <aside className="surface min-w-0 p-5 sm:p-6">
          <SectionHeader eyebrow={t('home.timelineEyebrow')} title={t('home.timelineTitle')}>
            {liveKey &&
              (streamDown ? (
                <span className="font-mono text-[10px] uppercase tracking-[0.12em] text-ink-muted">
                  {t('nav.reconnecting')}
                </span>
              ) : (
                <span
                  className="inline-flex items-center gap-1.5 font-mono text-[10px] tracking-[0.12em] text-success"
                  title={t('home.liveHint')}
                >
                  <span className="h-1.5 w-1.5 rounded-full bg-current animate-pulse-dot" aria-hidden />
                  {t('home.live')}
                </span>
              ))}
          </SectionHeader>
          {recent.length === 0 ? (
            <p className="mt-4 font-body text-body-md text-ink-light">{t('home.recentEmpty')}</p>
          ) : (
            <ol className="mt-4">
              {recent.map((task, index) => {
                const assignee = mariuses.find((m) => m.id === task.assigneeId);
                const status = normalizeStatus(task.status);
                return (
                  <li key={task.id} className="relative">
                    {index < recent.length - 1 && (
                      <span className="absolute bottom-0 left-[3px] top-3 w-px bg-line" aria-hidden />
                    )}
                    <Link to={wsHref(workspaceId, `/tasks/${task.id}`)} className="group relative flex gap-3 pb-[18px]">
                      <span
                        className={cn(
                          'relative z-[1] mt-[7px] h-[7px] w-[7px] shrink-0 rounded-full ring-4 ring-surface',
                          STATUS_DOT[status] ?? 'bg-ink-faint'
                        )}
                        aria-hidden
                      />
                      <div className="min-w-0 font-body text-body-sm leading-relaxed text-ink-light">
                        <p className="break-words">
                          <strong className="font-semibold text-ink-strong">
                            {assignee ? assignee.displayName || assignee.name : t('home.unassigned')}
                          </strong>{' '}
                          {task.identifier && <span className="task-code mr-1">{task.identifier}</span>}
                          <span className="transition-colors group-hover:text-sapphire-strong">{task.title}</span>
                        </p>
                        <small className="mt-0.5 block text-body-xs text-ink-muted">
                          {t(`tasks.status.${status}`, { defaultValue: task.status })} ·{' '}
                          {relativeTime(task.updatedAt ?? task.createdAt, t)}
                        </small>
                      </div>
                    </Link>
                  </li>
                );
              })}
            </ol>
          )}
        </aside>
      </div>

      <section className="flex min-w-0 flex-col gap-4">
        <SectionHeader eyebrow={t('home.projectsEyebrow')} title={t('home.projectsTitle')}>
          <Link to={wsHref(workspaceId, '/projects/new')} className="btn btn-secondary btn-sm">
            <Plus className="h-4 w-4" aria-hidden />
            {t('home.newProject')}
          </Link>
          <Link to={wsHref(workspaceId, '/projects')} className="btn-text">
            {t('home.allProjects')} <ArrowRight className="h-4 w-4" aria-hidden />
          </Link>
        </SectionHeader>
        {activeProjects.length === 0 ? (
          <div className="surface px-5 py-5 font-body text-body-md text-ink-light">{t('home.projectsEmpty')}</div>
        ) : (
          <div className="grid grid-cols-1 gap-3.5 md:grid-cols-2 xl:grid-cols-3">
            {activeProjects.map((project) => {
              const own = tasks.filter((tk) => tk.projectId === project.id).map((tk) => normalizeStatus(tk.status));
              const count = (s: string) => own.filter((x) => x === s).length;
              const segments = [
                { key: 'done', n: count('done'), cls: 'bg-success' },
                { key: 'review', n: count('in_review'), cls: 'bg-sapphire' },
                { key: 'progress', n: count('in_progress'), cls: 'bg-gold' },
                { key: 'blocked', n: count('blocked'), cls: 'bg-danger' },
                {
                  key: 'rest',
                  n: own.filter((x) => !['done', 'in_review', 'in_progress', 'blocked', 'cancelled'].includes(x)).length,
                  cls: 'bg-line-strong',
                },
              ];
              const total = own.filter((x) => x !== 'cancelled').length;
              const percent = total ? Math.round((count('done') / total) * 100) : 0;
              const about = project.objective || project.description;
              return (
                <Link
                  key={project.id}
                  to={wsHref(workspaceId, `/projects/${project.id}`)}
                  className="group flex min-w-0 flex-col rounded-lg border border-line bg-surface p-5 transition-[border-color,transform] hover:-translate-y-0.5 hover:border-sapphire"
                >
                  <div className="flex items-center justify-between gap-2">
                    <span className="task-code truncate">{project.key ?? ''}</span>
                    <StatusChip status={project.status} label={t(`projects.status.${project.status}`)} />
                  </div>
                  <h3 className="mt-3.5 break-words font-display text-[21px] font-normal leading-snug tracking-[-0.01em] text-ink-strong">
                    {project.name}
                  </h3>
                  {about && (
                    <p className="mt-1.5 line-clamp-2 break-words font-body text-body-sm text-ink-light">{about}</p>
                  )}
                  <div className="mt-auto pt-4">
                    <div className="mb-2 flex items-baseline justify-between gap-2 font-body text-body-xs text-ink-muted">
                      <span>{total > 0 ? t('home.doneOf', { done: count('done'), total }) : t('home.noTasks')}</span>
                      {total > 0 && <strong className="font-semibold text-ink-strong">{percent}%</strong>}
                    </div>
                    <div className="flex h-1.5 gap-0.5 overflow-hidden rounded-full bg-canvas-deep">
                      {segments
                        .filter((s) => s.n > 0)
                        .map((s) => (
                          <span key={s.key} className={s.cls} style={{ flexGrow: s.n }} />
                        ))}
                    </div>
                    {total > 0 && (
                      <div className="mt-2.5 flex flex-wrap gap-x-3.5 gap-y-1 font-body text-body-xs text-ink-light">
                        {segments
                          .filter((s) => s.n > 0)
                          .map((s) => (
                            <span key={s.key} className="inline-flex items-center gap-1.5">
                              <span className={cn('h-2 w-2 rounded-sm', s.cls)} aria-hidden />
                              {t(`home.bar.${s.key}`)} {s.n}
                            </span>
                          ))}
                      </div>
                    )}
                  </div>
                </Link>
              );
            })}
          </div>
        )}
      </section>

      <section className="surface min-w-0 p-5 sm:p-6">
        <SectionHeader eyebrow={t('home.teamEyebrow')} title={t('home.agentsTitle')}>
          <Link to={wsHref(workspaceId, '/agents')} className="btn btn-secondary btn-sm">
            <Plus className="h-4 w-4" aria-hidden />
            {t('home.addAgent')}
          </Link>
          <Link to={wsHref(workspaceId, '/agents')} className="btn-text">
            {t('home.allAgents')} <ArrowRight className="h-4 w-4" aria-hidden />
          </Link>
        </SectionHeader>
        {agentRows.length === 0 ? (
          <p className="mt-4 border-t border-line pt-4 font-body text-body-md text-ink-light">{t('home.agentsEmpty')}</p>
        ) : (
          <div className="mt-3 grid grid-cols-1 gap-x-6 lg:grid-cols-2">
            {agentRows.map((agent) => {
              const holding = holdingOf(agent);
              const name = agent.displayName || agent.name;
              return (
                <Link
                  key={agent.id}
                  to={wsHref(workspaceId, holding ? `/tasks/${holding.id}` : `/agents/${agent.id}`)}
                  className="group flex min-w-0 items-center gap-3 border-t border-line py-3.5"
                  aria-label={`${name} — ${holding ? t('home.viewTask') : t('home.profile')}`}
                >
                  <AgentAvatar name={name} status={agent.status} />
                  <div className="min-w-0 flex-1 font-body">
                    <p className="truncate text-body-md font-semibold text-ink-strong">
                      {name}
                      {agent.role && <span className="font-normal text-ink-muted"> · {agent.role}</span>}
                    </p>
                    {holding ? (
                      <>
                        <p className="truncate text-body-sm text-ink-light group-hover:text-sapphire-strong">
                          {holding.identifier && <span className="task-code mr-1.5">{holding.identifier}</span>}
                          {holding.title}
                        </p>
                        <p className="truncate text-body-xs text-ink-muted">
                          {t(`tasks.status.${normalizeStatus(holding.status)}`, { defaultValue: holding.status })}
                          {holding.drive ? ` · ${holding.drive}` : ''}
                        </p>
                      </>
                    ) : (
                      <p className="truncate text-body-sm text-ink-muted">{t('home.agentNoTask')}</p>
                    )}
                  </div>
                  <StatusChip status={agent.status} label={t(`directory.status.${agent.status}`, { defaultValue: agent.status })} />
                </Link>
              );
            })}
          </div>
        )}
      </section>
    </div>
  );
}
