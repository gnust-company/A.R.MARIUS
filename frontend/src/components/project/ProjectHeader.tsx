// The header every in-project page shares (board, plan, roster): a way back to the index, the
// project's key · phase, its name and objective, the chat with its Leader, a strip of real
// facts about it, and the tab row that moves between the three pages.
//
// The tabs are links to the existing routes rather than local state: each page loads its own
// data and keeps its own URL, so a tab can be bookmarked and the back button behaves.
import { useEffect, useState, type ReactNode } from 'react';
import { Link, useParams } from 'react-router';
import { useTranslation } from 'react-i18next';
import { ArrowLeft, CheckCheck, KanbanSquare, ListChecks, MessageCircle, UsersRound } from 'lucide-react';
import { EMPTY_CARD_COUNTS, useAppStore, type Project } from '@/store/appStore';
import * as api from '@/lib/api';
import { cn, wsHref } from '@/lib/utils';
import PageTitle from '@/components/PageTitle';
import AgentAvatar from '@/components/AgentAvatar';
import LeaderChatWidget from '@/components/LeaderChatWidget';
import { formatDate, projectCode } from '@/components/project/projectFormat';

export type ProjectTab = 'board' | 'plan' | 'roster';

const TABS: { key: ProjectTab; path: string; label: string; icon: typeof KanbanSquare }[] = [
  { key: 'board', path: '', label: 'projectView.tabBoard', icon: KanbanSquare },
  { key: 'plan', path: '/plan', label: 'projectView.tabPlan', icon: ListChecks },
  { key: 'roster', path: '/roster', label: 'projectView.tabRoster', icon: UsersRound },
];

function InfoCell({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="flex-[1_1_170px] min-w-0 flex flex-col justify-center gap-1.5 min-h-[84px] px-5 py-4 border-t border-l border-line">
      <span className="font-body text-[11px] text-ink-muted">{label}</span>
      <div className="min-w-0 font-body text-[14px] font-semibold text-ink-strong">{children}</div>
    </div>
  );
}

export default function ProjectHeader({
  project,
  active,
  actions,
}: {
  project: Project;
  active: ProjectTab;
  /** The page's own buttons, drawn after "Chat with the Leader". */
  actions?: ReactNode;
}) {
  const { t, i18n } = useTranslation();
  const { workspaceId } = useParams<{ workspaceId: string }>();
  const mariuses = useAppStore((s) => s.mariuses);
  const allTasks = useAppStore((s) => s.tasks);
  const hydrateProject = useAppStore((s) => s.hydrateProject);
  const [chatOpen, setChatOpen] = useState(false);

  // The plan page reads its own endpoints and never loads the project detail; the header needs
  // the seats and tasks, so it loads them when nobody has yet.
  const needsDetail = project.seats === undefined;
  useEffect(() => {
    if (needsDetail) void hydrateProject(project.id).catch(() => {});
  }, [needsDetail, project.id, hydrateProject]);

  // The viewer's own auto-approval switch (FR-036 → FR-038). It is not a project setting: every
  // patron has their own, and nobody switches it on for anyone else.
  const acceptsTasks = project.status === 'operating' || project.status === 'maintaining';
  const [autoApproval, setAutoApproval] = useState<boolean | null>(null);
  const [switching, setSwitching] = useState(false);
  useEffect(() => {
    let alive = true;
    api
      .getAutoApproval(project.id)
      .then((row) => alive && setAutoApproval(row.enabled))
      .catch(() => alive && setAutoApproval(null));
    return () => {
      alive = false;
    };
  }, [project.id]);

  const toggleAutoApproval = async () => {
    if (autoApproval === null) return;
    setSwitching(true);
    try {
      const row = await api.setAutoApproval(project.id, !autoApproval);
      setAutoApproval(row.enabled);
    } catch {
      // Keep what is shown: better unchanged than showing a choice the patron did not make.
    }
    setSwitching(false);
  };

  const seats = project.seats ?? [];
  const leaderSeat = seats.find((s) => s.role === 'leader');
  const leader = leaderSeat?.mariusId ? mariuses.find((m) => m.id === leaderSeat.mariusId) : undefined;
  const leaderName = leader ? leader.displayName || leader.name : null;
  const seatsTotal = project.seats ? seats.length : project.seatsTotal ?? 0;
  const seatsFilled = project.seats ? seats.filter((s) => s.mariusId).length : project.seatsFilled ?? 0;

  const tasks = allTasks.filter((tk) => tk.projectId === project.id && tk.status !== 'cancelled');
  const doneCount = tasks.filter((tk) => tk.status === 'done').length;
  const artifactCount = tasks.reduce((sum, tk) => sum + (tk.cardCounts ?? EMPTY_CARD_COUNTS).artifacts, 0);
  const created = formatDate(project.createdAt, i18n.language);

  return (
    <div className="flex flex-col">
      <Link
        to={wsHref(workspaceId, '/projects')}
        className="group inline-flex items-center gap-2 self-start min-h-[42px] -mt-2 mb-3 font-body text-[14px] font-medium text-ink-light hover:text-sapphire-strong transition-colors"
      >
        <ArrowLeft className="w-4 h-4 transition-transform group-hover:-translate-x-0.5" />
        {t('projectView.allProjects')}
      </Link>

      <PageTitle
        eyebrow={`${projectCode(project)} · ${t(`projects.status.${project.status}`)}`}
        title={project.name}
        subtitle={project.objective || project.description || undefined}
        actions={
          <>
            <button type="button" onClick={() => setChatOpen(true)} className="btn btn-secondary">
              <MessageCircle className="w-4 h-4" />
              {leaderName ? t('projectView.chatWith', { name: leaderName }) : t('leaderChat.title')}
            </button>
            {actions}
          </>
        }
      />

      {/* Facts about the project — only fields the server actually has. */}
      <section className="mt-6 overflow-hidden rounded-lg border border-line bg-surface">
        <div className="flex flex-wrap -mt-px -ml-px">
          <InfoCell label={t('projectView.infoLeader')}>
            {leader ? (
              <Link
                to={wsHref(workspaceId, `/agents/${leader.id}`)}
                className="inline-flex max-w-full items-center gap-2.5 hover:text-sapphire-strong transition-colors"
              >
                <AgentAvatar name={leaderName ?? ''} status={leader.status} size="sm" />
                <span className="truncate">{leaderName}</span>
              </Link>
            ) : (
              <span className="font-normal text-ink-muted">{t('projectView.noLeader')}</span>
            )}
          </InfoCell>
          <InfoCell label={t('projectView.infoTeam')}>
            {t('projectView.seatsFilled', { filled: seatsFilled, total: seatsTotal })}
          </InfoCell>
          <InfoCell label={t('projectView.infoAcceptance')}>
            {tasks.length > 0 ? (
              t('projectView.doneOfTotal', { done: doneCount, total: tasks.length })
            ) : (
              <span className="font-normal text-ink-muted">{t('projectView.noTasksYet')}</span>
            )}
          </InfoCell>
          {tasks.length > 0 && (
            <InfoCell label={t('projectView.infoArtifacts')}>
              {t('projectView.artifacts', { count: artifactCount })}
            </InfoCell>
          )}
          {created && <InfoCell label={t('projectView.infoCreated')}>{created}</InfoCell>}
          {project.githubUrl && (
            <InfoCell label={t('projectView.infoRepo')}>
              <a
                href={project.githubUrl}
                target="_blank"
                rel="noopener noreferrer"
                className="block truncate font-mono text-[12px] font-normal text-sapphire-strong hover:underline"
              >
                {project.githubUrl.replace(/^https?:\/\//, '')}
              </a>
            </InfoCell>
          )}
        </div>
      </section>

      {/* Tabs + the viewer's auto-approval switch */}
      <div className="mt-5 mb-5 flex flex-wrap items-center gap-x-6 gap-y-1">
        <nav aria-label={t('projectView.tabsLabel')} className="flex min-w-0 max-w-full overflow-x-auto no-scrollbar">
          {TABS.map((tab) => {
            const current = tab.key === active;
            return (
              <Link
                key={tab.key}
                to={wsHref(workspaceId, `/projects/${project.id}${tab.path}`)}
                aria-current={current ? 'page' : undefined}
                className={cn(
                  'inline-flex shrink-0 items-center gap-2 min-h-[48px] px-2.5 sm:px-3.5 border-b-2 font-body text-[14px] whitespace-nowrap transition-colors',
                  current
                    ? 'border-sapphire text-ink-strong'
                    : 'border-transparent text-ink-light hover:text-ink-strong hover:border-line-strong'
                )}
              >
                <tab.icon className="hidden sm:block w-[17px] h-[17px]" strokeWidth={1.7} />
                {t(tab.label)}
              </Link>
            );
          })}
        </nav>

        {/* Only once the project takes real work: before that there is no output to accept. */}
        {acceptsTasks && autoApproval !== null && (
          <label
            className="ml-auto inline-flex items-center gap-2 min-h-[44px] font-body text-[13px] text-ink-light cursor-pointer"
            title={autoApproval ? t('board.autoApprovalOn') : t('board.autoApprovalOff')}
          >
            <input
              type="checkbox"
              checked={autoApproval}
              disabled={switching}
              onChange={() => void toggleAutoApproval()}
              aria-describedby="auto-approval-explainer"
              className="w-[17px] h-[17px] accent-sapphire-strong"
            />
            <CheckCheck className="w-4 h-4" />
            {t('projectView.autoApprove')}
            <span id="auto-approval-explainer" className="sr-only">
              {autoApproval ? t('board.autoApprovalOn') : t('board.autoApprovalOff')}
            </span>
          </label>
        )}
      </div>

      {/* Floating Leader-chat bubble (project-only, bottom-right) — the header button opens it too. */}
      <LeaderChatWidget projectId={project.id} open={chatOpen} onOpenChange={setChatOpen} />
    </div>
  );
}
