// @ts-nocheck
import { useMemo } from 'react';
import { useNavigate, useParams } from 'react-router';
import { motion } from 'framer-motion';
import { Plus, Users, ScrollText, FolderOpen } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { useMockStore } from '@/store/mockStore';
import { wsHref } from '@/lib/utils';
import VellumPanel from '@/components/VellumPanel';
import StatusChip from '@/components/StatusChip';
import EmptyState from '@/components/EmptyState';
import PageTitle from '@/components/PageTitle';

// ─── Quill-in animation variants ─────────────────────────────────────────────

const containerVariants = {
  hidden: {},
  visible: {
    transition: {
      staggerChildren: 0.1,
    },
  },
};

const quillInVariants = {
  hidden: { opacity: 0, y: 24, filter: 'blur(2px)' },
  visible: {
    opacity: 1,
    y: 0,
    filter: 'blur(0px)',
    transition: { duration: 0.5, ease: [0, 0, 0.2, 1] as [number, number, number, number] },
  },
};

// ─── Component ───────────────────────────────────────────────────────────────

export default function Projects() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const { workspaceId } = useParams();
  const projects = useMockStore((s) => s.projects);
  const activeWorkspaceId = useMockStore((s) => s.activeWorkspaceId);
  const allTasks = useMockStore((s) => s.tasks);
  const workspaces = useMockStore((s) => s.workspaces);

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
      return {
        ...project,
        taskCount: tasks.length,
        seatsFilled: filledSeats,
        seatsTotal: totalSeats,
      };
    });
  }, [workspaceProjects, allTasks]);

  const isEmpty = projectsWithStats.length === 0;

  return (
    <div>
      {/* ─── Page Header ─── */}
      <motion.div
        className="flex items-center justify-between mb-8"
        initial="hidden"
        animate="visible"
        variants={containerVariants}
      >
        <div className="flex items-center gap-3">
          <motion.div variants={quillInVariants}>
            <PageTitle title={t('projects.titleInWorkspace', { workspaceName: activeWorkspace?.name || '' })} />
          </motion.div>
        </div>

        <motion.button
          variants={quillInVariants}
          onClick={() => navigate(wsHref(workspaceId, '/projects/new'))}
          className="inline-flex items-center gap-2 bg-[#C25E3A] hover:bg-[#D97B5A] text-white font-body font-medium text-body-md px-4 py-2.5 rounded-md transition-colors"
          style={{ transition: 'background-color 0.2s, transform 0.2s' }}
          onMouseEnter={(e) => { (e.target as HTMLElement).style.transform = 'translateY(-1px)'; }}
          onMouseLeave={(e) => { (e.target as HTMLElement).style.transform = 'translateY(0)'; }}
        >
          <Plus className="w-4 h-4" />
          {t('projects.newProject')}
        </motion.button>
      </motion.div>

      {/* ─── Empty State ─── */}
      {isEmpty && (
        <motion.div
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.5, delay: 0.2 }}
        >
          <EmptyState
            icon={FolderOpen}
            title={t('projects.emptyTitle')}
            description={t('projects.emptyDescription')}
            action={
              <button
                onClick={() => navigate(wsHref(workspaceId, '/projects/new'))}
                className="inline-flex items-center gap-2 bg-[#C25E3A] hover:bg-[#D97B5A] text-white font-body font-medium text-body-md px-6 py-3 rounded-md transition-colors"
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
          className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6"
          variants={containerVariants}
          initial="hidden"
          animate="visible"
        >
          {projectsWithStats.map((project) => (
            <motion.div
              key={project.id}
              variants={quillInVariants}
              onClick={() => navigate(wsHref(workspaceId, `/projects/${project.id}`))}
              className="cursor-pointer"
            >
              <VellumPanel
                hover
                className="h-full min-h-[240px] flex flex-col rounded-lg border-[#E3D7BC]"
              >
                {/* Title + status on the same row */}
                <div className="flex items-start justify-between gap-3 mb-3">
                  <h2 className="font-display text-display-sm text-ink leading-tight">
                    {project.name}
                  </h2>
                  <StatusChip
                    status={project.status}
                    label={t(`projects.status.${project.status}`)}
                  />
                </div>

                {/* Objective */}
                <p className="font-body text-body-md text-ink-light line-clamp-2 mb-4 flex-1">
                  {project.objective}
                </p>

                {/* Divider */}
                <div className="border-t border-[#E3D7BC] my-3" />

                {/* Stats row */}
                <div className="flex items-center gap-2 font-body text-body-sm text-ink-light mb-4">
                  <Users className="w-4 h-4 text-ink-muted" />
                  <span>
                    {t('projects.seatsCount', {
                      filled: project.seatsFilled,
                      total: project.seatsTotal,
                    })}
                  </span>
                  <span className="text-ink-muted mx-1">&middot;</span>
                  <ScrollText className="w-4 h-4 text-ink-muted" />
                  <span>{t('board.taskCount', { count: project.taskCount })}</span>
                </div>

                {/* Action link */}
                <div className="mt-auto">
                  {project.status === 'active' && (
                    <span className="font-body font-medium text-body-sm text-[#C25E3A]">
                      {t('projects.enterBoard')}
                    </span>
                  )}
                  {project.status === 'setup' && (
                    <span className="font-body font-medium text-body-sm text-[#C4903A]">
                      {t('projects.staffRoster')}
                    </span>
                  )}
                  {project.status === 'archived' && (
                    <span className="font-body font-medium text-body-sm text-ink-muted">
                      {t('projects.viewProject')}
                    </span>
                  )}
                </div>
              </VellumPanel>
            </motion.div>
          ))}

          {/* ─── Create Project Placeholder Card ─── */}
          <motion.div
            variants={quillInVariants}
            onClick={() => navigate(wsHref(workspaceId, '/projects/new'))}
            className="cursor-pointer"
          >
            <div className="h-full min-h-[240px] flex flex-col items-center justify-center text-center p-6 border-2 border-dashed border-[#E3D7BC] rounded-lg hover:border-[#C25E3A] hover:text-[#C25E3A] transition-colors group">
              <Plus className="w-10 h-10 text-ink-muted group-hover:text-[#C25E3A] mb-3 transition-colors" />
              <p className="font-body text-body-md text-ink-muted group-hover:text-[#C25E3A] transition-colors">
                {t('projects.createNewCard')}
              </p>
              <p className="font-body text-body-sm text-ink-muted group-hover:text-[#C25E3A] transition-colors mt-1">
                {t('projects.getStarted')}
              </p>
            </div>
          </motion.div>
        </motion.div>
      )}
    </div>
  );
}
