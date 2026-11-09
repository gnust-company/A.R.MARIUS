import { useEffect, useMemo, useState } from 'react';
import { Link, useParams } from 'react-router';
import { useTranslation } from 'react-i18next';
import type { TFunction } from 'i18next';
import { AlertTriangle, ArrowRight, FileQuestion, PenLine, Plus } from 'lucide-react';
import PageTitle from '@/components/PageTitle';
import StatusChip from '@/components/StatusChip';
import { getInbox, type InboxItemDTO } from '@/lib/api';
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

const RING: Record<string, string> = {
  working: 'bg-lapis-bg text-lapis-ink ring-lapis',
  online: 'bg-verdigris-bg text-verdigris-ink ring-verdigris',
  idle: 'bg-verdigris-bg text-verdigris-ink ring-verdigris',
  offline: 'bg-vellum text-ink-muted ring-transparent border-[1.5px] border-dashed border-ash',
};

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
  if (hour < 12) return 'home.greetingMorning';
  if (hour < 18) return 'home.greetingAfternoon';
  return 'home.greetingEvening';
}

function AgentAvatar({ agent, size = 'md' }: { agent: Marius; size?: 'sm' | 'md' }) {
  return (
    <span
      className={cn(
        'shrink-0 rounded-full flex items-center justify-center font-body font-semibold ring-2 ring-offset-2 ring-offset-paper',
        size === 'md' ? 'w-10 h-10 text-[15px]' : 'w-7 h-7 text-[12px]',
        RING[agent.status] ?? RING.offline
      )}
    >
      {(agent.displayName || agent.name).charAt(0).toUpperCase()}
    </span>
  );
}

function SectionHead({ title, link, linkLabel }: { title: string; link?: string; linkLabel?: string }) {
  return (
    <div className="flex items-baseline justify-between gap-3">
      <h2 className="font-display text-[22px] font-medium text-ink">{title}</h2>
      {link && linkLabel && (
        <Link to={link} className="font-body text-body-md font-medium text-terracotta hover:text-terracotta-dark">
          {linkLabel}
        </Link>
      )}
    </div>
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
  const [inbox, setInbox] = useState<InboxItemDTO[]>([]);

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
  }, [workspaceId]);

  const openTasks = tasks.filter((tk) => !CLOSED_STATUSES.has(normalizeStatus(tk.status)));
  const blocked = tasks.filter((tk) => normalizeStatus(tk.status) === 'blocked');
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
  const projectName = (id?: string | null) => projects.find((p) => p.id === id)?.name;

  const today = new Date().toLocaleDateString(i18n.language === 'vi' ? 'vi-VN' : 'en-US', {
    weekday: 'long',
    day: 'numeric',
    month: 'long',
  });

  return (
    <div className="max-w-[1240px] mx-auto flex flex-col gap-7 pb-10">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <p className="font-body text-body-sm font-medium text-ink-muted mb-2 first-letter:uppercase">{today}</p>
          <PageTitle
            illuminated
            title={t(greetingKey())}
            subtitle={t('home.summary', {
              waiting: inbox.length,
              running: running.length,
              blocked: blocked.length,
            })}
          />
        </div>
        <div className="flex flex-wrap gap-2.5">
          <Link
            to={wsHref(workspaceId, '/agents')}
            className="inline-flex items-center min-h-[44px] px-4 rounded-md border border-line-strong bg-paper font-body text-body-md font-medium text-ink hover:bg-inset transition-colors"
          >
            {t('home.addAgent')}
          </Link>
          <Link
            to={wsHref(workspaceId, '/projects/new')}
            className="inline-flex items-center gap-2 min-h-[44px] px-[18px] rounded-md bg-ink font-body text-body-md font-medium text-paper hover:bg-ink/85 transition-colors"
          >
            <Plus className="w-4 h-4" />
            {t('home.newProject')}
          </Link>
        </div>
      </div>

      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
        {[
          { label: t('home.statWaiting'), value: inbox.length, detail: null, tone: inbox.length > 0 },
          { label: t('home.statOpenTasks'), value: openTasks.length, detail: t('home.statOf', { total: tasks.length }) },
          {
            label: t('home.statAgents'),
            value: alive.length,
            detail: t('home.statAgentsDetail', { total: mariuses.length, running: running.length }),
          },
          { label: t('home.statProjects'), value: activeProjects.length, detail: null },
        ].map((stat) => (
          <div key={stat.label} className="bg-paper border border-line rounded-xl px-[18px] py-4">
            <div className="font-body text-body-sm text-ink-muted">{stat.label}</div>
            <div className="flex items-baseline gap-2 mt-1">
              <span className={cn('font-display text-[34px] font-medium leading-none', stat.tone ? 'text-gold-ink' : 'text-ink')}>
                {stat.value}
              </span>
              {stat.detail && <span className="font-body text-body-sm text-ink-muted">{stat.detail}</span>}
            </div>
          </div>
        ))}
      </div>

      <div className="flex flex-wrap gap-7 items-start">
        <div className="flex-[999_1_560px] min-w-0 flex flex-col gap-7">
          <section className="flex flex-col gap-3">
            <SectionHead title={t('home.waitingTitle')} link={wsHref(workspaceId, '/inbox')} linkLabel={t('home.openInbox')} />
            <div className="bg-paper border border-line rounded-xl divide-y divide-[#EFE5D1]">
              {inbox.length === 0 ? (
                <p className="px-5 py-5 font-body text-body-md text-ink-muted">{t('home.waitingEmpty')}</p>
              ) : (
                inbox.slice(0, 4).map((item) => {
                  const escalation = item.kind === 'escalation';
                  return (
                    <div key={item.id} className="flex flex-wrap items-center gap-4 px-5 py-4">
                      <span
                        className={cn(
                          'w-10 h-10 shrink-0 rounded-full flex items-center justify-center',
                          escalation ? 'bg-vermilion-bg text-vermilion-ink' : 'bg-gold-bg text-gold-ink'
                        )}
                      >
                        {escalation ? (
                          <AlertTriangle className="w-[18px] h-[18px]" />
                        ) : item.kind === 'review' || item.kind === 'sign_off' ? (
                          <PenLine className="w-[18px] h-[18px]" />
                        ) : (
                          <FileQuestion className="w-[18px] h-[18px]" />
                        )}
                      </span>
                      <div className="flex-[1_1_320px] min-w-0">
                        <div className="font-body text-body-xs font-medium text-gold-ink mb-0.5">
                          {t(`inbox.kind.${item.kind}`, { defaultValue: item.kind })}
                        </div>
                        <div className="font-body text-[15px] font-medium text-ink">{item.title}</div>
                        {item.body && (
                          <p className="font-body text-body-md text-ink-light mt-0.5 line-clamp-2">{item.body}</p>
                        )}
                        <div className="font-body text-body-sm text-ink-muted mt-1">
                          {[projectName(item.project_id), relativeTime(item.created_at, t)].filter(Boolean).join(' · ')}
                        </div>
                      </div>
                      <Link
                        to={wsHref(workspaceId, item.task_id ? `/tasks/${item.task_id}` : '/inbox')}
                        className="inline-flex items-center min-h-[44px] px-4 rounded-md bg-ink font-body text-body-md font-medium text-paper hover:bg-ink/85 transition-colors"
                      >
                        {t('home.open')}
                      </Link>
                    </div>
                  );
                })
              )}
            </div>
          </section>

          <section className="flex flex-col gap-3">
            <SectionHead title={t('home.agentsTitle')} link={wsHref(workspaceId, '/agents')} linkLabel={t('home.allAgents')} />
            <div className="bg-paper border border-line rounded-xl divide-y divide-[#EFE5D1]">
              {agentRows.length === 0 ? (
                <p className="px-5 py-5 font-body text-body-md text-ink-muted">{t('home.agentsEmpty')}</p>
              ) : (
                agentRows.map((agent) => {
                  const holding = holdingOf(agent);
                  return (
                    <div key={agent.id} className="flex flex-wrap items-center gap-4 px-5 py-4">
                      <AgentAvatar agent={agent} />
                      <div className="w-[150px] shrink-0 min-w-0">
                        <div className="font-body text-[15px] font-medium text-ink truncate">{agent.displayName || agent.name}</div>
                        <div className="font-body text-body-sm text-ink-muted truncate">{agent.role}</div>
                      </div>
                      <div className="flex-[1_1_300px] min-w-0 flex flex-col gap-1">
                        <div className="flex flex-wrap items-center gap-2">
                          <StatusChip status={agent.status} label={t(`directory.status.${agent.status}`, { defaultValue: agent.status })} />
                          {holding ? (
                            <span className="font-body text-body-md text-ink min-w-0 truncate">
                              {holding.identifier && (
                                <span className="font-mono text-mono-sm text-ink-muted mr-1.5">{holding.identifier}</span>
                              )}
                              {holding.title}
                            </span>
                          ) : (
                            <span className="font-body text-body-md text-ink-light">{t('home.agentNoTask')}</span>
                          )}
                        </div>
                        {holding && (
                          <span className="font-body text-body-sm text-ink-muted">
                            {t(`tasks.status.${normalizeStatus(holding.status)}`, { defaultValue: holding.status })}
                            {holding.drive ? ` · ${holding.drive}` : ''}
                          </span>
                        )}
                      </div>
                      <Link
                        to={wsHref(workspaceId, holding ? `/tasks/${holding.id}` : `/agents/${agent.id}`)}
                        className="inline-flex items-center min-h-[44px] px-4 rounded-md border border-line-strong bg-paper font-body text-body-md font-medium text-ink hover:bg-inset transition-colors"
                      >
                        {holding ? t('home.viewTask') : t('home.profile')}
                      </Link>
                    </div>
                  );
                })
              )}
            </div>
          </section>

          <section className="flex flex-col gap-3">
            <SectionHead title={t('home.projectsTitle')} />
            {activeProjects.length === 0 ? (
              <div className="bg-paper border border-line rounded-xl px-5 py-5 font-body text-body-md text-ink-muted">
                {t('home.projectsEmpty')}
              </div>
            ) : (
              activeProjects.map((project) => {
                const own = tasks.filter((tk) => tk.projectId === project.id).map((tk) => normalizeStatus(tk.status));
                const count = (s: string) => own.filter((x) => x === s).length;
                const segments = [
                  { key: 'done', n: count('done'), cls: 'bg-verdigris' },
                  { key: 'review', n: count('in_review'), cls: 'bg-gold' },
                  { key: 'progress', n: count('in_progress'), cls: 'bg-lapis' },
                  { key: 'blocked', n: count('blocked'), cls: 'bg-vermilion' },
                  {
                    key: 'rest',
                    n: own.filter((x) => !['done', 'in_review', 'in_progress', 'blocked', 'cancelled'].includes(x)).length,
                    cls: 'bg-line',
                  },
                ];
                const total = own.filter((x) => x !== 'cancelled').length;
                return (
                  <Link
                    key={project.id}
                    to={wsHref(workspaceId, `/projects/${project.id}`)}
                    className="group flex flex-col gap-3.5 bg-paper border border-line rounded-xl px-5 py-[18px] hover:border-line-strong transition-colors"
                  >
                    <div className="flex flex-wrap items-center gap-2.5">
                      <span className="font-display text-[20px] font-medium text-ink">{project.name}</span>
                      <StatusChip status={project.status} showDot={false} label={t(`projects.status.${project.status}`)} />
                      <span className="ml-auto font-body text-body-md text-ink-light">
                        {total > 0 ? t('home.doneOf', { done: count('done'), total }) : t('home.noTasks')}
                      </span>
                      <ArrowRight className="w-4 h-4 text-ink-muted group-hover:text-ink transition-colors" />
                    </div>
                    {total > 0 && (
                      <>
                        <div className="flex h-2.5 rounded-full overflow-hidden gap-0.5 bg-vellum">
                          {segments
                            .filter((s) => s.n > 0)
                            .map((s) => (
                              <span key={s.key} className={s.cls} style={{ flexGrow: s.n }} />
                            ))}
                        </div>
                        <div className="flex flex-wrap gap-4 font-body text-body-sm text-ink-light">
                          {segments
                            .filter((s) => s.n > 0)
                            .map((s) => (
                              <span key={s.key} className="inline-flex items-center gap-1.5">
                                <span className={cn('w-2 h-2 rounded-sm', s.cls)} />
                                {t(`home.bar.${s.key}`)} {s.n}
                              </span>
                            ))}
                        </div>
                      </>
                    )}
                  </Link>
                );
              })
            )}
          </section>
        </div>

        <aside className="flex-[1_1_300px] min-w-0 bg-inset border border-line rounded-xl px-[18px] pt-[18px] pb-2">
          <h2 className="font-display text-[20px] font-medium text-ink mb-2">{t('home.recentTitle')}</h2>
          {recent.length === 0 ? (
            <p className="py-3 font-body text-body-md text-ink-muted">{t('home.recentEmpty')}</p>
          ) : (
            <ol className="flex flex-col">
              {recent.map((task) => {
                const assignee = mariuses.find((m) => m.id === task.assigneeId);
                return (
                  <li key={task.id} className="border-b border-[#E9DEC8] last:border-b-0">
                    <Link to={wsHref(workspaceId, `/tasks/${task.id}`)} className="flex gap-3 py-3 group">
                      {assignee ? (
                        <AgentAvatar agent={assignee} size="sm" />
                      ) : (
                        <span className="w-7 h-7 shrink-0 rounded-full border-[1.5px] border-dashed border-ash" />
                      )}
                      <div className="min-w-0 font-body text-body-md text-ink-light leading-snug">
                        <div className="text-ink group-hover:text-terracotta transition-colors">
                          {task.identifier && <span className="font-mono text-mono-sm text-ink-muted mr-1.5">{task.identifier}</span>}
                          {task.title}
                        </div>
                        <div className="flex flex-wrap items-center gap-2 mt-1">
                          <StatusChip
                            status={normalizeStatus(task.status)}
                            label={t(`tasks.status.${normalizeStatus(task.status)}`, { defaultValue: task.status })}
                          />
                          <span className="text-body-xs text-ink-muted">{relativeTime(task.updatedAt ?? task.createdAt, t)}</span>
                        </div>
                      </div>
                    </Link>
                  </li>
                );
              })}
            </ol>
          )}
        </aside>
      </div>
    </div>
  );
}
