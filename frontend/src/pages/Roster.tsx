// @ts-nocheck
import { useState, useMemo, useEffect } from 'react';
import { useParams } from 'react-router';
import { useTranslation } from 'react-i18next';
import { motion, AnimatePresence } from 'framer-motion';
import {
  Check,
  Bot,
  Lock,
  AlertTriangle,
  Zap,
  Plus,
} from 'lucide-react';
import { useMockStore, type ProjectSeat, type Marius } from '@/store/mockStore';
import VellumPanel from '@/components/VellumPanel';
import StatusChip from '@/components/StatusChip';
import Modal from '@/components/Modal';
import PageTitle from '@/components/PageTitle';
import { cn } from '@/lib/utils';

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
        status === 'pending' && 'bg-status-pending',
        status === 'invited' && 'bg-status-invited',
        status === 'revoked' && 'bg-status-revoked',
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
  const particles = useMemo(() => {
    return Array.from({ length: 30 }, (_, i) => ({
      id: i,
      x: (Math.random() - 0.5) * 300,
      y: -(Math.random() * 200 + 50),
      rotation: Math.random() * 720 - 360,
      scale: 0.5 + Math.random() * 0.5,
      color: ['#C25E3A', '#D4A843', '#4A9E6B', '#E8C96A', '#D97B5A', '#A8D8B8'][
        Math.floor(Math.random() * 6)
      ],
    }));
  }, []);

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

// ─── Grant Seat Modal ────────────────────────────────────────────────────────

function GrantSeatModal({
  isOpen,
  onClose,
  roleKey,
  roleLabel,
  projectId,
  skillsRequired,
}: {
  isOpen: boolean;
  onClose: () => void;
  roleKey: string;
  roleLabel: string;
  projectId: string;
  skillsRequired: string[];
}) {
  const { t } = useTranslation();
  const mariuses = useMockStore((s) => s.mariuses);
  const project = useMockStore((s) => s.projects.find((p) => p.id === projectId));
  const grantSeat = useMockStore((s) => s.grantSeat);
  const [selectedAgentId, setSelectedAgentId] = useState<string | null>(null);

  // Available agents: approved (not invited/pending) and not already seated in this project
  const seatedMariusIds = new Set((project?.seats || []).map((s) => s.mariusId).filter(Boolean) || []);
  const availableAgents = mariuses.filter(
    (m) =>
      !['invited', 'pending', 'revoked'].includes(m.status) &&
      !seatedMariusIds.has(m.id)
  );

  const handleGrant = async () => {
    if (!selectedAgentId) return;
    await grantSeat(projectId, selectedAgentId, roleKey);
    setSelectedAgentId(null);
    onClose();
  };

  return (
    <Modal
      isOpen={isOpen}
      onClose={onClose}
      title={
        (() => {
          const full = t('roster.grantSeatTitle', { role: roleLabel });
          return (
            <span className="font-display text-ink">
              <span className="title-initial">{full.charAt(0)}</span>
              {full.slice(1)}
            </span>
          );
        })()
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
            onClick={handleGrant}
            disabled={!selectedAgentId}
            className={cn(
              'px-4 py-2 rounded-md font-body text-body-md font-medium transition-colors',
              selectedAgentId
                ? 'bg-terracotta text-white hover:bg-terracotta-light'
                : 'bg-vellum-dark text-ink-muted cursor-not-allowed'
            )}
          >
            {t('roster.grantSeat')}
          </button>
        </>
      }
    >
      <div className="space-y-4">
        {/* Agent list */}
        <div className="space-y-2">
          <p className="font-body text-body-sm font-medium text-ink">{t('roster.selectAgent')}</p>
          {availableAgents.length === 0 ? (
            <p className="font-body text-body-sm text-ink-muted italic">
              No available agents. Invite and approve agents first.
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
                {selectedAgentId === agent.id && (
                  <Check className="w-4 h-4 text-terracotta" />
                )}
              </button>
            ))
          )}
        </div>

        {/* Skills to install */}
        {skillsRequired.length > 0 && (
          <div className="pt-2 border-t border-vellum-dark">
            <p className="font-body text-body-xs text-ink-muted mb-1.5">
              {t('roster.skillsToInstall')}:
            </p>
            <div className="flex flex-wrap gap-1.5">
              {skillsRequired.map((skill) => (
                <span
                  key={skill}
                  className="px-2 py-0.5 rounded-sm bg-vellum-deep border border-vellum-dark font-body text-body-xs text-ink-light"
                >
                  {skill}
                </span>
              ))}
            </div>
          </div>
        )}
      </div>
    </Modal>
  );
}

// ─── Main Roster Page ────────────────────────────────────────────────────────

export default function Roster() {
  const { id: projectId } = useParams<{ id: string }>();
  const { t } = useTranslation();
  const projects = useMockStore((s) => s.projects);
  const mariuses = useMockStore((s) => s.mariuses);
  const isMock = useMockStore((s) => s.isMock);
  const hydrateProject = useMockStore((s) => s.hydrateProject);
  const hydrateWorkspace = useMockStore((s) => s.hydrateWorkspace);
  const project = projects.find((p) => p.id === projectId);

  const [grantModalRole, setGrantModalRole] = useState<{
    roleKey: string;
    roleLabel: string;
    skillsRequired: string[];
  } | null>(null);

  // Real-API mode: load the project roster + the workspace's agents on mount.
  useEffect(() => {
    if (isMock || !projectId) return;
    (async () => {
      await hydrateProject(projectId);
      const wsId = useMockStore.getState().projects.find((p) => p.id === projectId)?.workspaceId;
      if (wsId) await hydrateWorkspace(wsId);
    })();
  }, [isMock, projectId, hydrateProject, hydrateWorkspace]);

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
  const workerSeats = project.seats.filter((s) => s.role !== 'leader');

  const seatsTotal = project.seats.length;
  const seatsGranted = project.seats.filter((s) => s.mariusId).length;
  const seatsOnline = project.seats.filter((s) => {
    if (!s.mariusId) return false;
    const m = mariuses.find((m) => m.id === s.mariusId);
    return m?.status === 'online' || m?.status === 'working';
  }).length;

  const isFullyGranted = seatsGranted === seatsTotal;
  const isActive = project.status === 'active';
  const isSetup = project.status === 'setup';

  const progressPercent = seatsTotal > 0 ? (seatsGranted / seatsTotal) * 100 : 0;

  // Group worker seats by role. A plain derivation (no useMemo): it runs only after the
  // loading guards above, so no hook sits after an early return (rules-of-hooks, #56); the
  // React Compiler memoizes it automatically.
  const roleGroups: Record<string, { roleLabel: string; skillsRequired: string[]; seats: typeof workerSeats }> = {};
  workerSeats.forEach((seat) => {
    if (!roleGroups[seat.role]) {
      roleGroups[seat.role] = { roleLabel: seat.role, skillsRequired: [], seats: [] };
    }
    roleGroups[seat.role].seats.push(seat);
  });

  return (
    <div className="flex flex-col gap-6">
      {/* ─── Page Header ────────────────────────────────────────────── */}
      <motion.div
        initial={{ opacity: 0, y: 24, filter: 'blur(2px)' }}
        animate={{ opacity: 1, y: 0, filter: 'blur(0px)' }}
        transition={{ duration: 0.4, ease: [0, 0, 0.2, 1] as [number, number, number, number] }}
        className="flex items-center justify-between"
      >
        <div className="flex items-center gap-3">
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
                  isActive ? 'text-success' : isSetup ? 'text-warning' : 'text-ink-muted'
                )}
              >
                {isActive ? t('projects.status.active') : t('projects.status.setup')}
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
              <EmptySeatCard
                onGrant={() =>
                  setGrantModalRole({
                    roleKey: leaderSeat.role,
                    roleLabel: leaderSeat.role,
                    skillsRequired: [],
                  })
                }
              />
            )}
          </VellumPanel>
        )}
      </motion.div>

      {/* ─── Worker Roles Section ───────────────────────────────────── */}
      <motion.div
        initial={{ opacity: 0, y: 16 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ delay: 0.2, duration: 0.4 }}
      >
        <h2 className="font-display text-display-sm text-gold mb-3 flex items-center gap-2">
          <span className="w-10 h-0.5 bg-gold rounded-full" />
          {t('roster.workerRoles')}
        </h2>

        <div className="space-y-4">
          {Object.entries(roleGroups).map(([roleKey, group], groupIndex) => {
            const filledCount = group.seats.filter((s) => s.mariusId).length;
            return (
              <motion.div
                key={roleKey}
                initial={{ opacity: 0, y: 20 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{
                  delay: 0.25 + groupIndex * 0.12,
                  duration: 0.4,
                }}
              >
                <VellumPanel>
                  {/* Role header */}
                  <div className="flex items-start justify-between mb-2">
                    <div>
                      <div className="flex items-center gap-2 mb-1">
                        <h3 className="font-display text-display-sm text-ink">
                          {group.roleLabel}
                        </h3>
                        <span className="font-mono text-mono-sm text-ink-muted">
                          {t('roster.seatsUnit', { count: group.seats.length })}
                        </span>
                      </div>
                      <div className="flex flex-wrap gap-1.5 mb-1">
                        {[].map((skill) => (
                          <span
                            key={skill}
                            className="px-2 py-0.5 rounded-sm bg-vellum-deep border border-vellum-dark font-body text-body-xs text-ink-light"
                          >
                            {skill}
                          </span>
                        ))}
                      </div>
                      <p className="font-mono text-mono-sm text-ink-light">
                        {t('roster.seatsFilled', { filled: filledCount, total: group.seats.length })}
                      </p>
                    </div>
                  </div>

                  {/* Seats grid */}
                  <div className="space-y-2 mt-4">
                    {group.seats.map((seat, seatIndex) => (
                      <motion.div
                        key={`${seat.role}-${seatIndex}`}
                        initial={{ opacity: 0 }}
                        animate={{ opacity: 1 }}
                        transition={{ delay: 0.3 + seatIndex * 0.06 }}
                      >
                        <AnimatePresence mode="wait">
                          {seat.mariusId ? (
                            <GrantedSeatCard
                              key="granted"
                              seat={seat}
                              seatNumber={seatIndex + 1}
                            />
                          ) : (
                            <EmptySeatCard
                              key="empty"
                              seatNumber={seatIndex + 1}
                              onGrant={() =>
                                setGrantModalRole({
                                  roleKey: seat.role,
                                  roleLabel: group.roleLabel,
                                  skillsRequired: [],
                                })
                              }
                            />
                          )}
                        </AnimatePresence>
                      </motion.div>
                    ))}
                  </div>
                </VellumPanel>
              </motion.div>
            );
          })}
        </div>
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

      {/* ─── Grant Seat Modal ───────────────────────────────────────── */}
      <GrantSeatModal
        isOpen={grantModalRole !== null}
        onClose={() => setGrantModalRole(null)}
        roleKey={grantModalRole?.roleKey || ''}
        roleLabel={grantModalRole?.roleLabel || ''}
        projectId={projectId || ''}
        skillsRequired={grantModalRole?.skillsRequired || []}
      />
    </div>
  );
}

// ─── Granted Seat Card ───────────────────────────────────────────────────────

function GrantedSeatCard({
  seat,
  seatNumber: _seatNumber,
  showBadge = false,
}: {
  seat: ProjectSeat;
  seatNumber?: number;
  showBadge?: boolean;
}) {
  const { t } = useTranslation();
  const mariuses = useMockStore((s) => s.mariuses);
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
    </motion.div>
  );
}

// ─── Empty Seat Card ─────────────────────────────────────────────────────────

function EmptySeatCard({
  seatNumber,
  onGrant,
}: {
  seatNumber?: number;
  onGrant: () => void;
}) {
  const { t } = useTranslation();

  return (
    <div className="flex items-center gap-3 p-3 border-2 border-dashed border-vellum-dark rounded-md">
      <div className="w-9 h-9 rounded-full bg-vellum-deep border border-vellum-dark flex items-center justify-center">
        <Plus className="w-4 h-4 text-ink-muted" />
      </div>
      <div className="flex-1">
        <span className="font-body text-body-sm text-ink-muted">
          {seatNumber ? `Seat ${seatNumber}:` : ''} {t('roster.emptySeat')}
        </span>
      </div>
      <button
        onClick={onGrant}
        className={cn(
          'px-3 py-1.5 rounded-md font-body text-body-sm font-medium',
          'bg-vellum-deep text-terracotta border border-terracotta',
          'hover:bg-terracotta hover:text-white transition-colors'
        )}
      >
        {t('roster.grantSeat')}
      </button>
    </div>
  );
}
