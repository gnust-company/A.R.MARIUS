import { useState, useEffect } from 'react';
import { useParams, useNavigate } from 'react-router';
import { useTranslation } from 'react-i18next';
import { motion, AnimatePresence } from 'framer-motion';
import {
  Check,
  Bot,
  Lock,
  AlertTriangle,
  Zap,
  Plus,
  ChevronLeft,
  UserMinus,
} from 'lucide-react';
import { useAppStore, type ProjectSeat, type Marius } from '@/store/appStore';
import VellumPanel from '@/components/VellumPanel';
import StatusChip from '@/components/StatusChip';
import Modal from '@/components/Modal';
import PageTitle from '@/components/PageTitle';
import { cn, wsHref } from '@/lib/utils';

// ─── Status Dot ──────────────────────────────────────────────────────────────

function StatusDot({ status }: { status: string }) {
  return (
    <span
      className={cn(
        'w-2 h-2 rounded-full flex-shrink-0',
        status === 'online' && 'bg-status-online',
        status === 'working' && 'bg-status-working',
        status === 'idle' && 'bg-status-idle',
        status === 'offline' && 'bg-status-offline',
        status === 'hung' && 'bg-status-hung',
        status === 'checking' && 'bg-status-checking',
      )}
    />
  );
}

// ─── Agent Avatar ────────────────────────────────────────────────────────────

function AgentAvatar({ agent, size = 32 }: { agent: Marius; size?: number }) {
  return (
    <div
      className="rounded-full bg-vellum-dark overflow-hidden border border-vellum-dark flex-shrink-0"
      style={{ width: size, height: size }}
      title={agent.displayName || agent.name}
    >
      {agent.avatar ? (
        <img src={agent.avatar} alt={agent.displayName || agent.name} className="w-full h-full object-cover" />
      ) : (
        <div className="w-full h-full flex items-center justify-center text-ink-muted">
          <Bot className="w-4 h-4" />
        </div>
      )}
    </div>
  );
}

// ─── Confetti Particles ──────────────────────────────────────────────────────

function ConfettiBurst() {
  // Scattered once, in a lazy state initialiser rather than during render: the
  // burst must look the same for as long as it is on screen, and drawing random
  // numbers while rendering means a re-render reshuffles them mid-animation.
  const [particles] = useState(() =>
    Array.from({ length: 30 }, (_, i) => ({
      id: i,
      x: (Math.random() - 0.5) * 300,
      y: -(Math.random() * 200 + 50),
      rotation: Math.random() * 720 - 360,
      scale: 0.5 + Math.random() * 0.5,
      color: ['#C25E3A', '#D4A843', '#4A9E6B', '#E8C96A', '#D97B5A', '#A8D8B8'][
        Math.floor(Math.random() * 6)
      ],
    }))
  );

  return (
    <div className="absolute inset-0 overflow-hidden pointer-events-none">
      {particles.map((p) => (
        <motion.div
          key={p.id}
          className="absolute left-1/2 bottom-0 w-2 h-2 rounded-sm"
          style={{ backgroundColor: p.color }}
          initial={{ x: 0, y: 0, rotate: 0, opacity: 1, scale: 1 }}
          animate={{
            x: p.x,
            y: p.y,
            rotate: p.rotation,
            opacity: 0,
            scale: p.scale,
          }}
          transition={{ duration: 1.2, ease: [0.25, 0.46, 0.45, 0.94] as [number, number, number, number] }}
        />
      ))}
    </div>
  );
}

// ─── Add Agent Modal ─────────────────────────────────────────────────────────

/** Put an agent on this project, or in its leader seat. Two things to say — which agent, and
 *  (by which button opened this) whether it leads — and nothing else.
 *
 *  It used to be a *seat* dialog: the patron had already created a role, given it a title, a
 *  seat count, a description of the work and a list of skills, and this was step two. What an
 *  agent does is written on the agent (FR-007l), so step one is gone and so is this dialog's
 *  half of it. */
function AddAgentModal({
  isOpen,
  onClose,
  asLeader,
  projectId,
}: {
  isOpen: boolean;
  onClose: () => void;
  asLeader: boolean;
  projectId: string;
}) {
  const { t } = useTranslation();
  const mariuses = useAppStore((s) => s.mariuses);
  const project = useAppStore((s) => s.projects.find((p) => p.id === projectId));
  const seatLeader = useAppStore((s) => s.seatLeader);
  const addProjectMember = useAppStore((s) => s.addProjectMember);
  const [selectedAgentId, setSelectedAgentId] = useState<string | null>(null);

  // Anyone already on this project is not offered again — the server refuses a second seat,
  // and an option that can only fail is worse than no option.
  const seatedMariusIds = new Set((project?.seats || []).map((s) => s.mariusId).filter(Boolean));
  const availableAgents = mariuses.filter((m) => !seatedMariusIds.has(m.id));

  const handleAdd = async () => {
    if (!selectedAgentId) return;
    if (asLeader) await seatLeader(projectId, selectedAgentId);
    else await addProjectMember(projectId, selectedAgentId);
    setSelectedAgentId(null);
    onClose();
  };

  const title = asLeader ? t('roster.seatLeaderTitle') : t('roster.addAgentTitle');

  return (
    <Modal
      isOpen={isOpen}
      onClose={onClose}
      title={
        <span className="font-display text-ink">
          <span className="title-initial">{title.charAt(0)}</span>
          {title.slice(1)}
        </span>
      }
      footer={
        <>
          <button
            onClick={onClose}
            className="px-4 py-2 rounded-md font-body text-body-md font-medium bg-vellum-deep text-ink border border-vellum-dark hover:bg-vellum-dark transition-colors"
          >
            {t('common.cancel')}
          </button>
          <button
            onClick={handleAdd}
            disabled={!selectedAgentId}
            className={cn(
              'px-4 py-2 rounded-md font-body text-body-md font-medium transition-colors',
              selectedAgentId
                ? 'bg-terracotta text-white hover:bg-terracotta-light'
                : 'bg-vellum-dark text-ink-muted cursor-not-allowed'
            )}
          >
            {asLeader ? t('roster.seatLeader') : t('roster.addAgent')}
          </button>
        </>
      }
    >
      <div className="space-y-2">
        <p className="font-body text-body-sm font-medium text-ink">{t('roster.selectAgent')}</p>
        {availableAgents.length === 0 ? (
          <p className="font-body text-body-sm text-ink-muted italic">
            {t('roster.noAgentsLeft')}
          </p>
        ) : (
          availableAgents.map((agent) => (
            <button
              key={agent.id}
              onClick={() => setSelectedAgentId(agent.id)}
              className={cn(
                'w-full flex items-center gap-3 p-3 rounded-md border transition-all text-left',
                selectedAgentId === agent.id
                  ? 'border-terracotta bg-vellum shadow-sm'
                  : 'border-vellum-dark hover:border-vellum-dark hover:bg-vellum-deep'
              )}
            >
              <AgentAvatar agent={agent} size={36} />
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2">
                  <span className="font-body text-body-md font-medium text-ink">
                    {agent.displayName || agent.name}
                  </span>
                </div>
                <div className="flex items-center gap-2 mt-0.5">
                  <StatusDot status={agent.status} />
                  <span className="font-body text-body-xs text-ink-muted capitalize">
                    {agent.status}
                  </span>
                  <span className="font-mono text-mono-sm text-ink-muted">{agent.adapterType || '—'}</span>
                </div>
              </div>
              {selectedAgentId === agent.id && (
                <Check className="w-4 h-4 text-terracotta" />
              )}
            </button>
          ))
        )}
      </div>
    </Modal>
  );
}

// ─── Main Roster Page ────────────────────────────────────────────────────────

export default function Roster() {
  const { id: projectId, workspaceId } = useParams<{ id: string; workspaceId: string }>();
  const navigate = useNavigate();
  const { t } = useTranslation();
  const projects = useAppStore((s) => s.projects);
  const mariuses = useAppStore((s) => s.mariuses);
  const hydrateProject = useAppStore((s) => s.hydrateProject);
  const removeProjectMember = useAppStore((s) => s.removeProjectMember);
  const hydrateWorkspace = useAppStore((s) => s.hydrateWorkspace);
  const project = projects.find((p) => p.id === projectId);

  // Which door the dialog is open on: the leader seat, the team, or neither.
  const [adding, setAdding] = useState<'leader' | 'member' | null>(null);

  // Load the project roster + the workspace's agents on mount.
  useEffect(() => {
    if (!projectId) return;
    (async () => {
      await hydrateProject(projectId);
      const wsId = useAppStore.getState().projects.find((p) => p.id === projectId)?.workspaceId;
      if (wsId) await hydrateWorkspace(wsId);
    })();
  }, [projectId, hydrateProject, hydrateWorkspace]);

  if (!project) {
    return (
      <div className="flex flex-col items-center justify-center py-20">
        <h2 className="font-display text-display-md text-ink mb-2">{t('common.loading')}</h2>
      </div>
    );
  }

  // List-level projects (from `projectToVM`) carry no `seats` — only `projectDetailToVM`
  // (run by `hydrateProject`) fills them. On a fresh mount the first render sees a project
  // with `seats === undefined`, before the async hydrate lands; accessing `.find` on it
  // threw a TypeError and — with no ErrorBoundary — blanked the page (#56). Treat the
  // detail-not-yet-loaded state the same as not-loaded: show the loading gate.
  if (!project.seats) {
    return (
      <div className="flex flex-col items-center justify-center py-20">
        <h2 className="font-display text-display-md text-ink mb-2">{t('common.loading')}</h2>
      </div>
    );
  }

  // ─── Roster data calculations ───
  const leaderSeat = project.seats.find((s) => s.role === 'leader');
  const memberSeats = project.seats.filter((s) => s.role !== 'leader' && s.mariusId);

  const seatsTotal = project.seats.length;
  const seatsGranted = project.seats.filter((s) => s.mariusId).length;
  const seatsOnline = project.seats.filter((s) => {
    if (!s.mariusId) return false;
    const m = mariuses.find((m) => m.id === s.mariusId);
    return m?.status === 'online' || m?.status === 'working';
  }).length;

  const isFullyGranted = seatsGranted === seatsTotal;
  // Past the setup gate. A project leaves `setup` exactly when its roster is full and every
  // agent on it is online, so "not setup" *is* "the roster did its job" — which is what this
  // page is about. Reading it as operating/maintaining only was a leftover from before the
  // five phases: a project sitting in `planning` with everyone seated and online was drawn as
  // still waiting for them, under a chip that already said Planning.
  const isActive = project.status !== 'setup';
  // The team can still be changed while there is no work to orphan. A real task only exists
  // once the patron has approved the plan (FR-003), so that is the honest line.
  const teamIsStillOpen = project.status === 'setup' || project.status === 'planning';

  const progressPercent = seatsTotal > 0 ? (seatsGranted / seatsTotal) * 100 : 0;

  return (
    <div className="flex flex-col gap-6">
      {/* ─── Page Header ────────────────────────────────────────────── */}
      <motion.div
        initial={{ opacity: 0, y: 24, filter: 'blur(2px)' }}
        animate={{ opacity: 1, y: 0, filter: 'blur(0px)' }}
        transition={{ duration: 0.4, ease: [0, 0, 0.2, 1] as [number, number, number, number] }}
        className="flex items-end justify-between"
      >
        <div className="flex flex-col gap-3">
          <button
            onClick={() => navigate(wsHref(workspaceId, `/projects/${projectId}`))}
            className="inline-flex items-center gap-1 self-start px-2.5 py-1.5 rounded-md bg-vellum-deep border border-vellum-dark font-body text-body-sm text-ink hover:bg-vellum-dark transition-colors"
          >
            <ChevronLeft className="w-4 h-4" />
            {t('roster.backToBoard')}
          </button>
          <PageTitle title={t('roster.title')} />
        </div>
        <StatusChip status={project.status} label={t(`projects.status.${project.status}`)} />
      </motion.div>

      {/* ─── Progress Summary ───────────────────────────────────────── */}
      <motion.div
        initial={{ opacity: 0, y: 16 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ delay: 0.1, duration: 0.4 }}
      >
        <VellumPanel>
          <div className="flex items-center justify-between mb-2">
            <p className="font-body text-body-sm text-ink-light">
              {t('roster.progressSummary', { granted: seatsGranted, total: seatsTotal })}
              <span className="text-ink-muted mx-2">&middot;</span>
              <span className={cn('font-mono text-mono-sm', seatsOnline === seatsTotal ? 'text-success' : 'text-warning')}>
                {seatsOnline}/{seatsTotal} online
              </span>
              <span className="text-ink-muted mx-2">&middot;</span>
              <span
                className={cn(
                  'font-body text-body-sm font-medium',
                  isActive ? 'text-success' : 'text-warning'
                )}
              >
                {t(`projects.status.${project.status}`)}
              </span>
            </p>
            <span className="font-mono text-mono-md text-ink">{Math.round(progressPercent)}%</span>
          </div>

          {/* Progress bar */}
          <div className="w-full h-2 bg-vellum-dark rounded-full overflow-hidden">
            <motion.div
              className={cn(
                'h-full rounded-full',
                isActive ? 'bg-success' : 'bg-terracotta'
              )}
              initial={{ width: 0 }}
              animate={{ width: `${progressPercent}%` }}
              transition={{ duration: 0.8, ease: [0, 0, 0.2, 1] as [number, number, number, number] }}
            />
          </div>
        </VellumPanel>
      </motion.div>

      {/* ─── Project Leader Section ─────────────────────────────────── */}
      <motion.div
        initial={{ opacity: 0, y: 16 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ delay: 0.15, duration: 0.4 }}
      >
        <h2 className="font-display text-display-sm text-gold mb-3 flex items-center gap-2">
          <span className="w-10 h-0.5 bg-gold rounded-full" />
          {t('roster.projectLeader')}
        </h2>

        {leaderSeat && (
          <VellumPanel>
            {leaderSeat.mariusId ? (
              <GrantedSeatCard seat={leaderSeat} showBadge />
            ) : (
              <EmptySeatCard label={t('roster.emptyLeaderSeat')} onAdd={() => setAdding('leader')} />
            )}
          </VellumPanel>
        )}
      </motion.div>

      {/* ─── The team ───────────────────────────────────────────────── */}
      <motion.div
        initial={{ opacity: 0, y: 16 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ delay: 0.2, duration: 0.4 }}
      >
        <div className="flex items-baseline justify-between mb-3">
          <h2 className="font-display text-display-sm text-gold flex items-center gap-2">
            <span className="w-10 h-0.5 bg-gold rounded-full" />
            {t('roster.team')}
          </h2>
          <button
            onClick={() => setAdding('member')}
            className={cn(
              'inline-flex items-center gap-1.5 px-3 py-1.5 rounded-md font-body text-body-sm font-medium',
              'bg-vellum-deep text-terracotta border border-terracotta',
              'hover:bg-terracotta hover:text-white transition-colors'
            )}
          >
            <Plus className="w-4 h-4" />
            {t('roster.addAgent')}
          </button>
        </div>

        <VellumPanel>
          {/* One flat list. There is nothing to group by: an agent is on the project as
              itself, and what it does is written on the agent (FR-007l). */}
          {memberSeats.length === 0 ? (
            <p className="font-body text-body-sm text-ink-muted italic py-2">
              {t('roster.noTeamYet')}
            </p>
          ) : (
            <div className="space-y-2">
              <AnimatePresence initial={false}>
                {memberSeats.map((seat, seatIndex) => (
                  <motion.div
                    key={seat.mariusId}
                    initial={{ opacity: 0 }}
                    animate={{ opacity: 1 }}
                    exit={{ opacity: 0 }}
                    transition={{ delay: 0.05 * seatIndex }}
                  >
                    <GrantedSeatCard
                      seat={seat}
                      onRemove={
                        teamIsStillOpen
                          ? () => removeProjectMember(project.id, seat.mariusId!)
                          : undefined
                      }
                    />
                  </motion.div>
                ))}
              </AnimatePresence>
            </div>
          )}
        </VellumPanel>
      </motion.div>

      {/* ─── Activation Banner ──────────────────────────────────────── */}
      <motion.div
        initial={{ opacity: 0, y: 16 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ delay: 0.4, duration: 0.4 }}
        className="relative overflow-hidden rounded-lg mt-4"
      >
        {isActive ? (
          <div className="relative bg-success-bg border border-success/20 px-6 py-4 flex items-center gap-3 overflow-hidden">
            <ConfettiBurst />
            <Zap className="w-5 h-5 text-success flex-shrink-0 relative z-10" />
            <p className="font-body text-body-md text-success font-medium relative z-10">
              {t('roster.projectActive')}
            </p>
          </div>
        ) : isFullyGranted ? (
          <div className="bg-warning-bg border border-warning/20 px-6 py-4 flex items-center gap-3 rounded-lg">
            <AlertTriangle className="w-5 h-5 text-warning flex-shrink-0" />
            <p className="font-body text-body-md text-warning font-medium">
              {t('roster.waitingOnline')}
            </p>
          </div>
        ) : (
          <div className="bg-error-bg border border-error/20 px-6 py-4 flex items-center gap-3 rounded-lg">
            <Lock className="w-5 h-5 text-error flex-shrink-0" />
            <p className="font-body text-body-md text-error font-medium">
              {t('roster.allGranted')}
            </p>
          </div>
        )}
      </motion.div>

      {/* ─── Add Agent Modal ────────────────────────────────────────── */}
      <AddAgentModal
        isOpen={adding !== null}
        onClose={() => setAdding(null)}
        asLeader={adding === 'leader'}
        projectId={projectId || ''}
      />
    </div>
  );
}

// ─── Granted Seat Card ───────────────────────────────────────────────────────

// A granted seat is identified by who sits in it, not by its index — only the
// empty card needs a number to refer to.
function GrantedSeatCard({
  seat,
  showBadge = false,
  onRemove,
}: {
  seat: ProjectSeat;
  showBadge?: boolean;
  onRemove?: () => void;
}) {
  const { t } = useTranslation();
  const mariuses = useAppStore((s) => s.mariuses);
  const agent = mariuses.find((m) => m.id === seat.mariusId);

  if (!agent) return null;

  return (
    <motion.div
      initial={{ opacity: 0, scale: 0.9 }}
      animate={{ opacity: 1, scale: 1 }}
      transition={{ duration: 0.3, ease: [0.34, 1.56, 0.64, 1] as [number, number, number, number] }}
      className="flex items-center gap-3 p-3 bg-vellum rounded-md border border-vellum-dark"
    >
      <AgentAvatar agent={agent} size={36} />

      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2">
          <span className="font-body text-body-md font-medium text-ink">
            {agent.displayName || agent.name}
          </span>
          <span className="font-body text-body-xs text-ink-light">{agent.role}</span>
        </div>
        <div className="flex items-center gap-2 mt-0.5">
          <StatusDot status={agent.status} />
          <span className="font-body text-body-xs text-ink-muted capitalize">
            {agent.status}
          </span>
          <span className="font-mono text-mono-sm text-ink-muted">{agent.adapterType || '—'}</span>
        </div>
      </div>

      {showBadge && (
        <span className="flex items-center gap-1 px-2 py-0.5 rounded-full bg-success-bg text-success font-body text-body-xs font-medium">
          <Check className="w-3 h-3" />
          {t('roster.granted')}
        </span>
      )}

      {/* Only while the project is still being set up. Past that the team is settled, and
          the way somebody leaves a running project is not a button on this list. */}
      {onRemove && (
        <button
          onClick={onRemove}
          title={t('roster.removeAgent')}
          className="p-1.5 rounded-md text-ink-muted hover:text-error hover:bg-error-bg transition-colors"
        >
          <UserMinus className="w-4 h-4" />
        </button>
      )}
    </motion.div>
  );
}

// ─── Empty Seat Card ─────────────────────────────────────────────────────────

function EmptySeatCard({ label, onAdd }: { label: string; onAdd: () => void }) {
  const { t } = useTranslation();

  return (
    <div className="flex items-center gap-3 p-3 border-2 border-dashed border-vellum-dark rounded-md">
      <div className="w-9 h-9 rounded-full bg-vellum-deep border border-vellum-dark flex items-center justify-center">
        <Plus className="w-4 h-4 text-ink-muted" />
      </div>
      <div className="flex-1">
        <span className="font-body text-body-sm text-ink-muted">{label}</span>
      </div>
      <button
        onClick={onAdd}
        className={cn(
          'px-3 py-1.5 rounded-md font-body text-body-sm font-medium',
          'bg-vellum-deep text-terracotta border border-terracotta',
          'hover:bg-terracotta hover:text-white transition-colors'
        )}
      >
        {t('roster.seatLeader')}
      </button>
    </div>
  );
}
