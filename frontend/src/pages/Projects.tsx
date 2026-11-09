import { useEffect, useMemo } from 'react';
import { Link, useNavigate, useParams } from 'react-router';
import { motion } from 'framer-motion';
import { Plus, Users, ScrollText, FolderOpen, ArrowRight } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { useAppStore, type ProjectPhase } from '@/store/appStore';
import { cn, wsHref } from '@/lib/utils';
import StatusChip from '@/components/StatusChip';
import EmptyState from '@/components/EmptyState';
import PageTitle from '@/components/PageTitle';

/** The board's eleven spellings of a status, folded to the backend's eight (same fold as Home). */
function normalizeStatus(status: string): string {
  const s = status.replace(/-/g, '_');
  if (s === 'review') return 'in_review';
  if (s === 'pending') return 'todo';
  return s;
}

/** What the card offers next, by phase: the board once work runs, the roster or the plan
 *  while the project is still being set up — those two are the patron's move, so they read
 *  in the "needs you" colour. */
const NEXT_STEP: Record<ProjectPhase, { key: string; tone: string }> = {
  setup: { key: 'projects.staffRoster', tone: 'text-gold-ink' },
  planning: { key: 'projects.openPlan', tone: 'text-gold-ink' },
  operating: { key: 'projects.enterBoard', tone: 'text-terracotta group-hover:text-terracotta-dark' },
  maintaining: { key: 'projects.enterBoard', tone: 'text-terracotta group-hover:text-terracotta-dark' },
  closed: { key: 'projects.viewProject', tone: 'text-ink-light' },
};

// One short fade for the whole grid: the cards are the page, so they must never wait behind a
// staggered entrance.
const fadeIn = {
  initial: { opacity: 0, y: 6 },
  animate: { opacity: 1, y: 0 },
  transition: { duration: 0.2 },
};

// ─── Component ───────────────────────────────────────────────────────────────

export default function Projects() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const { workspaceId } = useParams();
  const projects = useAppStore((s) => s.projects);
  const activeWorkspaceId = useAppStore((s) => s.activeWorkspaceId);
  const allTasks = useAppStore((s) => s.tasks);
  const hydrateProject = useAppStore((s) => s.hydrateProject);
  const workspaces = useAppStore((s) => s.workspaces);

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
      const tasks = allTasks.filter((t) => t.projectId === project.id);
      // Prefer the detail-level `seats` array (authoritative once a project is opened); fall
      // back to the list-level counts from `ProjectOut` so a project the user hasn't opened
      // this session still shows its real roster fill instead of 0/0.
      const hasDetail = project.seats !== undefined;
      const filledSeats = hasDetail
        ? project.seats!.filter((s) => s.mariusId !== null).length
        : project.seatsFilled ?? 0;
      const totalSeats = hasDetail ? project.seats!.length : project.seatsTotal ?? 0;
      // Progress by task status. Only as good as the tasks already in the store: the list
      // endpoint carries no per-status counts, so a project nobody has opened this session
      // has none here and the bar stays hidden.
      const statuses = tasks.map((tk) => normalizeStatus(tk.status));
      const count = (s: string) => statuses.filter((x) => x === s).length;
      const segments = [
        { key: 'done', n: count('done'), cls: 'bg-verdigris' },
        { key: 'review', n: count('in_review'), cls: 'bg-gold' },
        { key: 'progress', n: count('in_progress'), cls: 'bg-lapis' },
        { key: 'blocked', n: count('blocked'), cls: 'bg-vermilion' },
        {
          key: 'rest',
          n: statuses.filter((x) => !['done', 'in_review', 'in_progress', 'blocked', 'cancelled'].includes(x)).length,
          cls: 'bg-line-strong',
        },
      ].filter((s) => s.n > 0);
      return {
        ...project,
        taskCount: tasks.length,
        doneCount: count('done'),
        openTotal: statuses.filter((x) => x !== 'cancelled').length,
        segments,
        seatsFilled: filledSeats,
        seatsTotal: totalSeats,
      };
    });
  }, [workspaceProjects, allTasks]);

  // The list response carries no task counts, and the board loads tasks per project — so a
  // card read "0 tasks" until its board had been opened once. Load each project's tasks
  // here, the same way Home does for its project summaries.
  const projectKey = workspaceProjects.map((p) => p.id).join(',');
  useEffect(() => {
    projectKey.split(',').filter(Boolean).forEach((id) => void hydrateProject(id).catch(() => {}));
  }, [projectKey, hydrateProject]);

  const isEmpty = projectsWithStats.length === 0;

  return (
    <div className="mx-auto w-full max-w-[1240px] flex flex-col gap-7 pb-10">
      {/* ─── Page Header ─── */}
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div className="min-w-0">
          <PageTitle title={t('projects.titleInWorkspace', { workspaceName: activeWorkspace?.name || '' })} />
        </div>
        <button
          onClick={() => navigate(wsHref(workspaceId, '/projects/new'))}
          className="inline-flex items-center gap-2 min-h-[44px] px-[18px] rounded-md bg-ink font-body text-body-md font-medium text-paper hover:bg-ink/85 transition-colors"
        >
          <Plus className="w-4 h-4" />
          {t('projects.newProject')}
        </button>
      </div>

      {/* ─── Empty State ─── */}
      {isEmpty && (
        <motion.div {...fadeIn}>
          <EmptyState
            icon={FolderOpen}
            title={t('projects.emptyTitle')}
            description={t('projects.emptyDescription')}
            action={
              <button
                onClick={() => navigate(wsHref(workspaceId, '/projects/new'))}
                className="inline-flex items-center gap-2 min-h-[44px] px-[18px] rounded-md bg-paper border border-line-strong font-body text-body-md font-medium text-ink hover:bg-inset transition-colors"
              >
                <Plus className="w-4 h-4" />
                {t('projects.createButton')}
              </button>
            }
          />
        </motion.div>
      )}

      {/* ─── Project Cards Grid ─── */}
      {!isEmpty && (
        <motion.div
          {...fadeIn}
          className="grid gap-4 grid-cols-[repeat(auto-fill,minmax(min(100%,340px),1fr))]"
        >
          {projectsWithStats.map((project) => {
            const next = NEXT_STEP[project.status] ?? NEXT_STEP.closed;
            return (
              <Link
                key={project.id}
                to={wsHref(workspaceId, `/projects/${project.id}`)}
                className="group flex flex-col gap-3.5 min-w-0 bg-paper border border-line rounded-xl px-5 py-[18px] hover:border-line-strong transition-colors"
              >
                {/* Name, key and phase */}
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0">
                    <h2 className="font-display text-[20px] font-medium leading-tight text-ink break-words">
                      {project.name}
                    </h2>
                    {project.key && (
                      <span className="font-mono text-mono-sm text-ink-muted">{project.key}</span>
                    )}
                  </div>
                  <StatusChip
                    status={project.status}
                    showDot={false}
                    label={t(`projects.status.${project.status}`)}
                  />
                </div>

                {/* Objective, or the description when no objective was written */}
                {(project.objective || project.description) && (
                  <p className="font-body text-body-md text-ink-light line-clamp-2">
                    {project.objective || project.description}
                  </p>
                )}

                {/* Progress by task status — the same bar as the front page */}
                {project.openTotal > 0 && (
                  <div className="flex flex-col gap-2">
                    <div className="flex h-2 rounded-full overflow-hidden gap-0.5 bg-inset">
                      {project.segments.map((s) => (
                        <span key={s.key} className={s.cls} style={{ flexGrow: s.n }} />
                      ))}
                    </div>
                    <div className="flex flex-wrap gap-x-3.5 gap-y-1 font-body text-body-sm text-ink-light">
                      {project.segments.map((s) => (
                        <span key={s.key} className="inline-flex items-center gap-1.5">
                          <span className={cn('w-2 h-2 rounded-sm', s.cls)} />
                          {t(`home.bar.${s.key}`)} {s.n}
                        </span>
                      ))}
                    </div>
                  </div>
                )}

                {/* Meta + next step, pinned to the bottom so cards in a row line up */}
                <div className="mt-auto pt-3 border-t border-line flex flex-wrap items-center gap-x-4 gap-y-2 font-body text-body-sm text-ink-light">
                  <span className="inline-flex items-center gap-1.5">
                    <Users className="w-4 h-4 text-ink-muted" />
                    {t('projects.seatsCount', { filled: project.seatsFilled, total: project.seatsTotal })}
                  </span>
                  <span className="inline-flex items-center gap-1.5">
                    <ScrollText className="w-4 h-4 text-ink-muted" />
                    {project.openTotal > 0
                      ? t('home.doneOf', { done: project.doneCount, total: project.openTotal })
                      : t('board.taskCount', { count: project.taskCount })}
                  </span>
                  <span className={cn('ml-auto inline-flex items-center gap-1 font-medium transition-colors', next.tone)}>
                    {t(next.key)}
                    <ArrowRight className="w-4 h-4" />
                  </span>
                </div>
              </Link>
            );
          })}

          {/* ─── Create Project Placeholder Card ─── */}
          <button
            onClick={() => navigate(wsHref(workspaceId, '/projects/new'))}
            className="min-h-[180px] flex flex-col items-center justify-center text-center gap-1 p-6 border-[1.5px] border-dashed border-line-strong rounded-xl text-ink-light hover:bg-paper hover:text-ink transition-colors"
          >
            <span className="w-10 h-10 mb-2 rounded-full bg-inset border border-line flex items-center justify-center">
              <Plus className="w-5 h-5" />
            </span>
            <span className="font-body text-[15px] font-medium">{t('projects.createNewCard')}</span>
            <span className="font-body text-body-sm text-ink-muted">{t('projects.getStarted')}</span>
          </button>
        </motion.div>
      )}
    </div>
  );
}
