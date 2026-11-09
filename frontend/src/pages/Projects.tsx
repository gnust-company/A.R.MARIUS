import { useEffect, useMemo, useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router';
import { motion } from 'framer-motion';
import { Plus, FolderOpen, ArrowUpRight, CalendarDays, Search } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { useAppStore, type ProjectPhase } from '@/store/appStore';
import { cn, wsHref } from '@/lib/utils';
import EmptyState from '@/components/EmptyState';
import PageTitle from '@/components/PageTitle';
import AgentAvatar from '@/components/AgentAvatar';
import { formatDate, projectCode } from '@/components/project/projectFormat';

/** The board's eleven spellings of a status, folded to the backend's eight (same fold as Home). */
function normalizeStatus(status: string): string {
  const s = status.replace(/-/g, '_');
  if (s === 'review') return 'in_review';
  if (s === 'pending') return 'todo';
  return s;
}

/** What the row offers next, by phase: the board once work runs, the roster or the plan
 *  while the project is still being set up — those two are the patron's move, so they read
 *  in the "needs you" colour. */
const NEXT_STEP: Record<ProjectPhase, { key: string; tone: string }> = {
  setup: { key: 'projects.staffRoster', tone: 'text-gold' },
  planning: { key: 'projects.openPlan', tone: 'text-gold' },
  operating: { key: 'projects.enterBoard', tone: 'text-ink-muted group-hover:text-sapphire-strong' },
  maintaining: { key: 'projects.enterBoard', tone: 'text-ink-muted group-hover:text-sapphire-strong' },
  closed: { key: 'projects.viewProject', tone: 'text-ink-muted' },
};

const PHASE_ORDER: ProjectPhase[] = ['setup', 'planning', 'operating', 'maintaining', 'closed'];

// The ledger's columns from lg up; below that each row becomes a card.
const LEDGER_COLS =
  'lg:grid lg:grid-cols-[minmax(260px,1.55fr)_minmax(150px,.75fr)_minmax(130px,.6fr)_minmax(170px,.8fr)_92px] lg:gap-6 lg:items-center';

// ─── Component ───────────────────────────────────────────────────────────────

export default function Projects() {
  const { t, i18n } = useTranslation();
  const navigate = useNavigate();
  const { workspaceId } = useParams();
  const projects = useAppStore((s) => s.projects);
  const activeWorkspaceId = useAppStore((s) => s.activeWorkspaceId);
  const allTasks = useAppStore((s) => s.tasks);
  const mariuses = useAppStore((s) => s.mariuses);
  const hydrateProject = useAppStore((s) => s.hydrateProject);
  const workspaces = useAppStore((s) => s.workspaces);
  const [query, setQuery] = useState('');
  const [phase, setPhase] = useState<ProjectPhase | 'all'>('all');

  const activeWorkspace = useMemo(
    () => workspaces.find((w) => w.id === activeWorkspaceId) || workspaces[0],
    [workspaces, activeWorkspaceId]
  );

  // Filter projects for active workspace, or show all if none selected
  const workspaceProjects = useMemo(() => {
    if (!activeWorkspaceId) return projects;
    return projects.filter((p) => p.workspaceId === activeWorkspaceId);
  }, [projects, activeWorkspaceId]);

  // Compute derived stats for each project
  const projectsWithStats = useMemo(() => {
    return workspaceProjects.map((project) => {
      const statuses = allTasks
        .filter((tk) => tk.projectId === project.id)
        .map((tk) => normalizeStatus(tk.status));
      // Prefer the detail-level `seats` array (authoritative once a project is opened); fall
      // back to the list-level counts from `ProjectOut` so a project the user hasn't opened
      // this session still shows its real roster fill instead of 0/0.
      const hasDetail = project.seats !== undefined;
      const seats = project.seats ?? [];
      const seatsFilled = hasDetail ? seats.filter((s) => s.mariusId !== null).length : project.seatsFilled ?? 0;
      const seatsTotal = hasDetail ? seats.length : project.seatsTotal ?? 0;
      // Leader first, then the rest of whoever sits on the project.
      const leaderSeat = seats.find((s) => s.role === 'leader');
      const leader = leaderSeat?.mariusId ? mariuses.find((m) => m.id === leaderSeat.mariusId) : undefined;
      const team = [...seats]
        .sort((a, b) => Number(b.role === 'leader') - Number(a.role === 'leader'))
        .map((s) => (s.mariusId ? mariuses.find((m) => m.id === s.mariusId) : undefined))
        .filter((m): m is NonNullable<typeof m> => Boolean(m));
      // Progress by task status. Only as good as the tasks already in the store: the list
      // endpoint carries no per-status counts, so the effect below loads each project's tasks.
      const live = statuses.filter((x) => x !== 'cancelled');
      const doneCount = live.filter((x) => x === 'done').length;
      return {
        ...project,
        liveTotal: live.length,
        doneCount,
        openCount: live.length - doneCount,
        progress: live.length ? Math.round((doneCount / live.length) * 100) : 0,
        seatsFilled,
        seatsTotal,
        leader,
        team,
      };
    });
  }, [workspaceProjects, allTasks, mariuses]);

  // The list response carries no task counts, and the board loads tasks per project — so a
  // row read "0 tasks" until its board had been opened once. Load each project's tasks
  // here, the same way Home does for its project summaries.
  const projectKey = workspaceProjects.map((p) => p.id).join(',');
  useEffect(() => {
    projectKey.split(',').filter(Boolean).forEach((id) => void hydrateProject(id).catch(() => {}));
  }, [projectKey, hydrateProject]);

  // Workspace-wide figures for the summary strip — all counted, none estimated.
  const openTasks = projectsWithStats.reduce((sum, p) => sum + p.openCount, 0);
  const agentsTakingPart = new Set(
    projectsWithStats.flatMap((p) => (p.seats ?? []).map((s) => s.mariusId).filter(Boolean))
  ).size;

  // Only the phases some project is actually in become filters.
  const phases = PHASE_ORDER.filter((ph) => workspaceProjects.some((p) => p.status === ph));

  const visible = projectsWithStats.filter((p) => {
    if (phase !== 'all' && p.status !== phase) return false;
    const needle = query.trim().toLocaleLowerCase();
    if (!needle) return true;
    return `${p.key ?? ''} ${p.name} ${p.objective ?? ''} ${p.description ?? ''}`.toLocaleLowerCase().includes(needle);
  });

  const isEmpty = projectsWithStats.length === 0;
  const newProject = () => navigate(wsHref(workspaceId, '/projects/new'));

  return (
    <div className="mx-auto w-full max-w-[1240px] flex flex-col pb-10">
      {/* ─── Page Header ─── */}
      <PageTitle
        eyebrow={activeWorkspace?.name ? `${activeWorkspace.name} · ${t('projectView.indexEyebrow')}` : t('projectView.indexEyebrow')}
        title={t('projects.title')}
        subtitle={t('projectView.indexSubtitle')}
        actions={
          <button onClick={newProject} className="btn btn-primary">
            <Plus className="w-4 h-4" />
            {t('projects.newProject')}
          </button>
        }
      />

      {/* ─── Empty State ─── */}
      {isEmpty && (
        <motion.div initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.2 }} className="mt-8">
          <EmptyState
            icon={FolderOpen}
            title={t('projects.emptyTitle')}
            description={t('projects.emptyDescription')}
            action={
              <button onClick={newProject} className="btn btn-secondary">
                <Plus className="w-4 h-4" />
                {t('projects.createButton')}
              </button>
            }
          />
        </motion.div>
      )}

      {!isEmpty && (
        <>
          {/* ─── Summary strip ─── */}
          <section
            aria-label={t('projectView.summaryLabel')}
            className="mt-7 mb-7 grid grid-cols-3 border-y border-line-strong lg:grid-cols-[repeat(3,minmax(150px,190px))_minmax(260px,1fr)]"
          >
            {[
              { n: projectsWithStats.length, label: t('projectView.statProjects') },
              { n: openTasks, label: t('projectView.statOpenTasks') },
              { n: agentsTakingPart, label: t('projectView.statAgents') },
            ].map((stat, i) => (
              <div
                key={stat.label}
                className={cn(
                  'flex flex-col justify-start min-h-[92px] lg:min-h-[106px] py-4 lg:py-6 px-3 sm:px-6 border-l border-line',
                  i === 0 && 'border-l-0 pl-0 sm:pl-0'
                )}
              >
                <strong className="font-display text-[32px] lg:text-[37px] font-normal leading-none text-ink-strong">{stat.n}</strong>
                <span className="mt-2 font-body text-[12px] leading-snug text-ink-light">{stat.label}</span>
              </div>
            ))}
            <p className="col-span-3 lg:col-span-1 flex items-center gap-3.5 border-t border-line lg:border-t-0 lg:border-l py-4 lg:py-5 lg:pl-7 font-body text-[14px] leading-relaxed text-ink-light">
              <FolderOpen className="w-[22px] h-[22px] shrink-0 text-sapphire-strong" strokeWidth={1.6} />
              {t('projectView.indexNote')}
            </p>
          </section>

          {/* ─── Search + phase filter ─── */}
          <div className="mb-5 flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
            <label className="flex w-full md:w-[min(440px,100%)] min-h-[46px] items-center gap-2.5 rounded-md border border-field-line bg-field px-3.5 focus-within:border-sapphire-strong focus-within:ring-[3px] focus-within:ring-sapphire/15 transition-colors">
              <Search className="w-[18px] h-[18px] shrink-0 text-ink-muted" />
              <input
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder={t('projectView.searchPlaceholder')}
                aria-label={t('projectView.searchLabel')}
                className="min-w-0 flex-1 bg-transparent font-body text-[15px] text-ink placeholder:text-ink-muted outline-none"
              />
            </label>
            {phases.length > 1 && (
              <div role="group" aria-label={t('projectView.filterLabel')} className="flex gap-1 overflow-x-auto no-scrollbar -mx-4 px-4 md:mx-0 md:px-0">
                {(['all', ...phases] as const).map((ph) => {
                  const count = ph === 'all' ? workspaceProjects.length : workspaceProjects.filter((p) => p.status === ph).length;
                  return (
                    <button
                      key={ph}
                      onClick={() => setPhase(ph)}
                      aria-pressed={phase === ph}
                      className={cn(
                        'inline-flex shrink-0 items-center gap-2 min-h-[40px] px-3.5 rounded-md font-body text-[13px] whitespace-nowrap transition-colors',
                        phase === ph
                          ? 'bg-sapphire-soft text-ink-strong font-medium'
                          : 'text-ink-light hover:bg-surface-hover hover:text-ink-strong'
                      )}
                    >
                      {ph === 'all' ? t('projectView.filterAll') : t(`projects.status.${ph}`)}
                      <span className="font-mono text-[10px] text-ink-muted">{count}</span>
                    </button>
                  );
                })}
              </div>
            )}
          </div>

          {/* ─── The ledger ─── */}
          <section aria-label={t('projectView.listLabel')} className="border-t border-line-strong">
            <div className={cn('hidden min-h-[45px] px-[18px] font-mono text-[10px] uppercase tracking-[0.1em] text-ink-muted', LEDGER_COLS)}>
              <span>{t('projectView.colProject')}</span>
              <span>{t('projectView.colProgress')}</span>
              <span>{t('projectView.colTeam')}</span>
              <span>{t('projectView.colCreated')}</span>
              <span aria-hidden />
            </div>

            {visible.map((project, index) => {
              const next = NEXT_STEP[project.status] ?? NEXT_STEP.closed;
              const created = formatDate(project.createdAt, i18n.language);
              const leaderName = project.leader ? project.leader.displayName || project.leader.name : null;
              return (
                <motion.div
                  key={project.id}
                  initial={{ opacity: 0, y: 10 }}
                  animate={{ opacity: 1, y: 0 }}
                  transition={{ delay: Math.min(index, 8) * 0.04, duration: 0.25 }}
                  className="border-t border-line [&:nth-child(2)]:border-t-0"
                >
                  <Link
                    to={wsHref(workspaceId, `/projects/${project.id}`)}
                    className={cn(
                      'group grid grid-cols-[minmax(0,1fr)_auto] gap-x-3 gap-y-4 py-5 px-1 lg:px-[18px] lg:py-[22px] lg:min-h-[130px] transition-colors hover:bg-surface/70',
                      LEDGER_COLS
                    )}
                  >
                    {/* Folio + name + phase · open tasks */}
                    <span className="flex min-w-0 items-center gap-3.5 lg:gap-4">
                      <span className="grid shrink-0 place-items-center w-[54px] h-[54px] lg:w-[66px] lg:h-[66px] rounded-full border border-line-strong font-mono text-[11px] lg:text-[12px] tracking-[0.04em] text-sapphire-strong transition-colors group-hover:border-sapphire group-hover:bg-sapphire-soft">
                        {projectCode(project)}
                      </span>
                      <span className="min-w-0">
                        <strong className="block font-display text-[20px] lg:text-[24px] font-normal leading-tight tracking-[-0.015em] text-ink-strong break-words">
                          {project.name}
                        </strong>
                        <small className="mt-1.5 block font-body text-[12px] text-ink-light">
                          {t(`projects.status.${project.status}`)}
                          {' · '}
                          {project.liveTotal > 0
                            ? t('projectView.openTasks', { count: project.openCount })
                            : t('projectView.noTasksYet')}
                        </small>
                      </span>
                    </span>

                    {/* Progress: tasks done out of those still alive */}
                    <span className="col-span-2 lg:col-span-1 order-3 lg:order-none grid gap-2.5">
                      <span className="flex items-baseline justify-between gap-2">
                        <strong className="font-body text-[15px] font-semibold text-ink-strong">{project.progress}%</strong>
                        <small className="font-body text-[12px] text-ink-light">
                          {t('projectView.doneOfTotal', { done: project.doneCount, total: project.liveTotal })}
                        </small>
                      </span>
                      <span className="block h-[5px] overflow-hidden rounded-full bg-line">
                        <span className="block h-full rounded-full bg-sapphire" style={{ width: `${project.progress}%` }} />
                      </span>
                    </span>

                    {/* Team: who sits on it, leader first */}
                    <span className="col-span-2 lg:col-span-1 order-4 lg:order-none flex flex-wrap items-center gap-x-3 gap-y-2 lg:flex-col lg:items-start">
                      {project.team.length > 0 && (
                        <span className="flex pl-2">
                          {project.team.slice(0, 4).map((agent) => (
                            <AgentAvatar
                              key={agent.id}
                              name={agent.displayName || agent.name}
                              status={agent.status}
                              size="sm"
                              className="-ml-2 ring-2 ring-canvas"
                            />
                          ))}
                        </span>
                      )}
                      <small className="font-body text-[12px] text-ink-light">
                        {t('projectView.seats', { filled: project.seatsFilled, total: project.seatsTotal })}
                      </small>
                    </span>

                    {/* When it was set up, and who leads it */}
                    <span className="col-span-2 lg:col-span-1 order-5 lg:order-none flex items-start gap-2.5 text-ink-light">
                      <CalendarDays className="mt-0.5 w-4 h-4 shrink-0" strokeWidth={1.6} />
                      <span className="min-w-0 flex flex-wrap items-baseline gap-x-2.5 lg:block">
                        {created && <strong className="block font-body text-[14px] font-medium text-ink">{created}</strong>}
                        <small className="lg:mt-1 block font-body text-[12px] text-ink-light">
                          {leaderName ? t('projectView.ledBy', { name: leaderName }) : t('projectView.noLeader')}
                        </small>
                      </span>
                    </span>

                    {/* Where the row leads */}
                    <span className={cn('order-2 lg:order-none flex flex-col items-end gap-1.5 transition-[color,transform] group-hover:translate-x-[3px] group-hover:-translate-y-[3px]', next.tone)}>
                      <ArrowUpRight className="w-[22px] h-[22px]" strokeWidth={1.6} />
                      <small className="hidden sm:block font-body text-[11px] whitespace-nowrap">{t(next.key)}</small>
                    </span>
                  </Link>
                </motion.div>
              );
            })}

            {visible.length === 0 && (
              <div className="flex flex-col items-center gap-2 border-t border-line py-14 text-center">
                <Search className="w-7 h-7 text-ink-muted" strokeWidth={1.5} />
                <h3 className="mt-1 font-display text-[22px] font-normal text-ink-strong">{t('projectView.noMatchTitle')}</h3>
                <p className="font-body text-[14px] text-ink-light">{t('projectView.noMatchBody')}</p>
                <button
                  onClick={() => {
                    setQuery('');
                    setPhase('all');
                  }}
                  className="btn btn-secondary mt-3"
                >
                  {t('projectView.clearFilters')}
                </button>
              </div>
            )}
          </section>
        </>
      )}
    </div>
  );
}
