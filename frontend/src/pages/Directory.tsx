import { useState, useMemo, useCallback } from 'react';
import { useNavigate, useParams } from 'react-router';
import { motion } from 'framer-motion';
import {
  Users,
  Plus,
  Search,
  Check,
  Lock,
  Star,
  Server,
  Loader2,
  Bot,
  Clock,
  WifiOff,
  Activity,
  Zap,
  AlertTriangle,
} from 'lucide-react';
import { useAppStore } from '@/store/appStore';
import type { Marius, AgentStatus, WorkplaceChoice } from '@/store/appStore';
import VellumPanel from '@/components/VellumPanel';
import EmptyState from '@/components/EmptyState';
import Modal from '@/components/Modal';
import ConfirmDialog from '@/components/ConfirmDialog';
import RuntimeOptionFields from '@/components/RuntimeOptionFields';
import PageTitle from '@/components/PageTitle';
import { cn, wsHref } from '@/lib/utils';
import { errorText } from '@/lib/errors';
import { useTranslation } from 'react-i18next';

// ─── Animation Variants ──────────────────────────────────────────────────────

const containerVariants = {
  hidden: { opacity: 0 },
  visible: {
    opacity: 1,
    transition: { staggerChildren: 0.08, delayChildren: 0.2 },
  },
};

const cardVariants = {
  hidden: { opacity: 0, y: 24, filter: 'blur(2px)' },
  visible: {
    opacity: 1,
    y: 0,
    filter: 'blur(0px)',
    transition: { duration: 0.5, ease: [0, 0, 0.2, 1] as [number, number, number, number] },
  },
};

// ─── Status Configuration ────────────────────────────────────────────────────

const STATUS_CONFIG: Record<
  AgentStatus,
  { color: string; pulse: boolean; label: string; icon: typeof Zap }
> = {
  online: { color: '#4A9E6B', pulse: true, label: 'Online', icon: Zap },
  working: { color: '#D4A843', pulse: true, label: 'Working', icon: Activity },
  idle: { color: '#A89880', pulse: false, label: 'Idle', icon: Clock },
  offline: { color: '#8B7A6A', pulse: false, label: 'Offline', icon: WifiOff },
};

// There is no adapter picker any more. It offered three choices of which only one was ever
// registered, and the real answer — which tool runs this agent — follows from the workplace
// the person picks, which is a thing they can actually see and reason about (FR-007g).

// ─── Component: Status Dot ───────────────────────────────────────────────────

function StatusDot({ status, size = 8 }: { status: AgentStatus; size?: number }) {
  const config = STATUS_CONFIG[status] || STATUS_CONFIG.offline;
  return (
    <span
      className={cn(
        'rounded-full flex-shrink-0',
        config.pulse && 'animate-pulse-dot'
      )}
      style={{
        width: size,
        height: size,
        backgroundColor: config.color,
        boxShadow: config.pulse ? `0 0 6px ${config.color}80` : 'none',
      }}
    />
  );
}

// ─── Component: Agent Card ───────────────────────────────────────────────────

function AgentCard({
  agent,
  onDesignate,
}: {
  agent: Marius;
  onDesignate: (id: string) => void;
}) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const { workspaceId } = useParams();
  const config = STATUS_CONFIG[agent.status] || STATUS_CONFIG.offline;

  const StatusIcon = config.icon;
  const displayName = agent.displayName || agent.name;
  const agentSkills = agent.skills || [];

  // Click the card → the agent's page, which is where an agent is managed (FR-007o): renaming,
  // settings and removal all live there rather than behind a menu on every card. The one button
  // left on the card stops propagation so acting on an agent never doubles as opening it.
  const openDetail = () => navigate(wsHref(workspaceId, `/agents/${agent.id}`));

  return (
    <motion.div variants={cardVariants} layout>
      <VellumPanel
        className="relative h-full cursor-pointer"
        onClick={openDetail}
        role="button"
        tabIndex={0}
        onKeyDown={(e) => {
          if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); openDetail(); }
        }}
      >
        {/* Top row: status dot + avatar + name + WA badge + menu */}
        <div className="flex items-start gap-3">
          <div className="flex items-center gap-2 flex-shrink-0 mt-1">
            <StatusDot status={agent.status} />
          </div>

          {/* Avatar */}
          <div
            className="w-10 h-10 rounded-full overflow-hidden flex-shrink-0 border-2 flex items-center justify-center"
            style={{ borderColor: config.color }}
          >
            {agent.avatar ? (
              <img
                src={agent.avatar}
                alt={displayName}
                className="w-full h-full object-cover"
              />
            ) : (
              <Bot className="w-5 h-5 text-ink-muted" />
            )}
          </div>

          {/* Name + Role */}
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-2 flex-wrap">
              <h3
                className="font-['Fraunces',Georgia,serif] text-[22px] font-medium text-[#2A2318] leading-tight"
              >
                {displayName}
              </h3>
              {agent.isWorkspaceAgent === true && (
                <span
                  className="inline-flex items-center gap-0.5 px-2 py-0.5 rounded-full text-[11px] font-medium bg-[#D4A843] text-[#2A2318]"
                >
                  <Star className="w-3 h-3" /> {t('directory.workspaceAgent')}
                </span>
              )}
            </div>
            <div className="flex items-center gap-2 mt-1">
              <span
                className="inline-flex items-center gap-1 text-[11px] font-medium"
                style={{ color: config.color }}
              >
                <StatusIcon className="w-3 h-3" />
                {t('directory.status.' + agent.status)}
              </span>
            </div>
          </div>

        </div>

        {/* Where it works — the CLI and the machine, which is what tells two agents apart at a
            glance (FR-007o). The status is already said once, beside the name. */}
        <div className="mt-3 flex items-center gap-1.5 text-[12px] font-mono text-[#6B5E4E]">
          <Server className="w-3.5 h-3.5 flex-shrink-0" aria-hidden />
          <span className="truncate">
            {agent.runtime
              ? t('agentDetail.runtimeLine', {
                  cli: agent.runtime.cli_kind,
                  machine: agent.runtime.machine_name,
                })
              : t('agentDetail.runtimeNone')}
          </span>
        </div>

        {/* Skills */}
        {agentSkills.length > 0 && (
          <div className="mt-3 flex flex-wrap gap-1.5">
            {agentSkills.slice(0, 3).map((skill) => (
              <span
                key={skill}
                className="px-2 py-0.5 rounded-full text-[11px] font-medium bg-[#E3D7BC] text-[#6B5E4E]"
              >
                {skill}
              </span>
            ))}
            {agentSkills.length > 3 && (
              <span className="px-2 py-0.5 rounded-full text-[11px] font-medium text-[#A89880]">
                {t('directory.moreSkills', { count: agentSkills.length - 3 })}
              </span>
            )}
          </div>
        )}

        {/* Contextual Actions */}
        <div className="mt-4 flex items-center gap-2">
          {agent.status === 'online' && agent.isWorkspaceAgent !== true && (
            <button
              onClick={(e) => { e.stopPropagation(); onDesignate(agent.id); }}
              className="inline-flex items-center gap-1.5 px-4 py-2 rounded-md text-[13px] font-medium border border-[#D4A843] text-[#D4A843] hover:bg-[#D4A843] hover:text-[#2A2318] transition-all"
            >
              <Star className="w-3.5 h-3.5" />
              {t('directory.actions.designate')}
            </button>
          )}
        </div>

      </VellumPanel>
    </motion.div>
  );
}

// ═══════════════════════════════════════════════════════════════════════════════
// MAIN PAGE: Directory
// ═══════════════════════════════════════════════════════════════════════════════

export default function Directory() {
  const { t } = useTranslation();
  const mariuses = useAppStore((s) => s.mariuses);
  const skills = useAppStore((s) => s.skills);
  const inviteNewAgent = useAppStore((s) => s.inviteNewAgent);
  const listWorkplaces = useAppStore((s) => s.listWorkplaces);
  const designateWorkspaceAgent = useAppStore((s) => s.designateWorkspaceAgent);
  const activeWorkspaceId = useAppStore((s) => s.activeWorkspaceId);

  // The sitting host — designating anyone else is a swap and asks for confirmation (#32).
  // Scoped to the active workspace: the store holds every workspace's mariuses.
  const currentHost = useMemo(
    () =>
      mariuses.find((m) => m.workspaceId === activeWorkspaceId && m.isWorkspaceAgent === true),
    [mariuses, activeWorkspaceId]
  );

  // ── Designate state ────────────────────────────────────────────────────────
  // Renaming, the runtime settings and removal moved to the agent's own page (FR-007o).
  const [designatingAgent, setDesignatingAgent] = useState<Marius | null>(null);

  // ── Filter State ───────────────────────────────────────────────────────────
  const [searchQuery, setSearchQuery] = useState('');
  const [statusFilter, setStatusFilter] = useState<string>('all');

  // ── Invite Modal State ─────────────────────────────────────────────────────
  const [inviteModalOpen, setInviteModalOpen] = useState(false);
  const [agentName, setAgentName] = useState('');
  // What the agent is told to be, and what the team calls it. Two boxes rather than one
  // because only the first is ever sent to the agent (FR-007i, FR-007j).
  const [instructions, setInstructions] = useState('');
  const [agentDescription, setAgentDescription] = useState('');
  // Where the new agent will work. Read when the form opens rather than held in the store:
  // an agent is attached to one workplace for life (FR-007), so this list has to be the one
  // that is true at the moment of choosing, not one cached from an earlier visit.
  const [workplaces, setWorkplaces] = useState<WorkplaceChoice[]>([]);
  const [workplaceId, setWorkplaceId] = useState('');
  // What the person picked out of what the chosen workplace offers (FR-007k). Keyed by the
  // server's name for each setting, never by a flag: this screen has no idea that one of them
  // becomes `--effort` on the machine, and it must not learn.
  const [runtimeOptions, setRuntimeOptions] = useState<Record<string, string>>({});
  const [workplacesLoading, setWorkplacesLoading] = useState(false);
  // The workplace currently picked, and therefore what it says its tool takes (FR-007k).
  const chosenWorkplace = workplaces.find((w) => w.id === workplaceId);
  // Why a refused invite was refused. The workplace list was true when this form opened;
  // a CLI uninstalled a minute later makes the chosen one stale, and the server says so in
  // a coded refusal. Swallowing it would leave the person clicking a button that does
  // nothing and says nothing.
  const [inviteError, setInviteError] = useState('');
  const [selectedSkillIds, setSelectedSkillIds] = useState<string[]>([]);
  const [makeWorkspaceAgent, setMakeWorkspaceAgent] = useState(false);
  const [inviteSwapConfirmOpen, setInviteSwapConfirmOpen] = useState(false);
  const [sending, setSending] = useState(false);

  // ── Filter Agents ──────────────────────────────────────────────────────────
  const filteredAgents = useMemo(() => {
    let filtered = [...mariuses];

    if (searchQuery.trim()) {
      const q = searchQuery.toLowerCase();
      filtered = filtered.filter(
        (m) =>
          (m.displayName || m.name).toLowerCase().includes(q) ||
          m.role.toLowerCase().includes(q) ||
          (m.adapterType || '').toLowerCase().includes(q) ||
          (m.skills || []).some((s) => s.toLowerCase().includes(q))
      );
    }

    if (statusFilter !== 'all') {
      filtered = filtered.filter((m) => m.status === statusFilter);
    }

    // Sort: online/working first, then by name
    filtered.sort((a, b) => {
      const score = (m: Marius) => {
        if (m.status === 'online') return 3;
        if (m.status === 'working') return 2;
        if (m.status === 'idle') return 1;
        return 0;
      };
      return score(b) - score(a) || (a.displayName || a.name).localeCompare(b.displayName || b.name);
    });

    return filtered;
  }, [mariuses, searchQuery, statusFilter]);

  // ── Handlers ───────────────────────────────────────────────────────────────
  const resetInviteForm = () => {
    setAgentName('');
    setInstructions('');
    setAgentDescription('');
    setWorkplaces([]);
    setWorkplaceId('');
    setRuntimeOptions({});
    setInviteError('');
    setSelectedSkillIds([]);
    setMakeWorkspaceAgent(false);
  };

  const handleOpenInvite = () => {
    resetInviteForm();
    setInviteModalOpen(true);
    setWorkplacesLoading(true);
    listWorkplaces()
      .then((rows) => {
        setWorkplaces(rows);
        // One workplace is not a choice, so make it rather than ask for it. More than one
        // stays blank: picking for the patron is picking which of their machines this agent
        // lives on for good, and that is not a decision to make on their behalf.
        setWorkplaceId(rows.length === 1 ? rows[0].id : '');
      })
      .catch(() => setWorkplaces([]))
      .finally(() => setWorkplacesLoading(false));
  };

  const doInvite = async () => {
    if (!agentName.trim() || !workplaceId || sending) return;
    setSending(true);
    setInviteError('');
    try {
      // A name and a workplace is the whole of it (FR-007g). Nothing is dialled out to and
      // nothing is pushed, so there is no send to wait on or report.
      await inviteNewAgent({
        name: agentName.trim(),
        instructions: instructions.trim(),
        description: agentDescription.trim(),
        workplaceId,
        skillIds: selectedSkillIds,
        // Only what was actually chosen. A blank travelling as an empty string would be a
        // key the server has to reason about, when what it means is *nothing was picked*.
        runtimeOptions: Object.fromEntries(
          Object.entries(runtimeOptions).filter(([, value]) => value !== ''),
        ),
        isWorkspaceAgent: makeWorkspaceAgent,
      });
      setInviteModalOpen(false);
    } catch (e) {
      // Same cleanup on both paths instead of a `finally`: the React Compiler cannot
      // lower `finally` and gives up on the whole component when it meets one. The
      // refusal is worded from its code, so the person reads why in their own language
      // rather than watching a button do nothing (FR-084a).
      setSending(false);
      setInviteError(errorText(e, t));
      return;
    }
    setSending(false);
  };

  const handleInvite = () => {
    // Seating a new host over a sitting one is a swap \u2014 confirm before inviting (#32).
    if (makeWorkspaceAgent && currentHost) {
      setInviteSwapConfirmOpen(true);
      return;
    }
    void doInvite();
  };

  const handleDesignate = useCallback(
    (id: string) => {
      // Real endpoint via the store (#32). A sitting host makes this a swap — confirm.
      const agent = useAppStore.getState().mariuses.find((m) => m.id === id);
      if (!agent) return;
      const host = useAppStore
        .getState()
        .mariuses.find(
          (m) => m.workspaceId === agent.workspaceId && m.isWorkspaceAgent === true
        );
      if (host && host.id !== id) {
        setDesignatingAgent(agent);
        return;
      }
      void designateWorkspaceAgent(id);
    },
    [designateWorkspaceAgent]
  );

  const handleCloseInvite = () => {
    setInviteModalOpen(false);
  };

  const toggleSkill = (skillId: string) => {
    setSelectedSkillIds((prev) =>
      prev.includes(skillId) ? prev.filter((s) => s !== skillId) : [...prev, skillId]
    );
  };

  // ── Render ─────────────────────────────────────────────────────────────────

  return (
    <div className="min-h-[100dvh]">
      {/* Page Header */}
      <motion.div
        initial={{ opacity: 0, y: 24, filter: 'blur(2px)' }}
        animate={{ opacity: 1, y: 0, filter: 'blur(0px)' }}
        transition={{ duration: 0.5, ease: [0, 0, 0.2, 1] as [number, number, number, number] }}
        className="flex items-center justify-between mb-6"
      >
        <div className="flex items-center gap-3">
          <PageTitle title={t('directory.pageTitle')} subtitle={t('directory.agentsInWorkspace', { count: mariuses.length })} />
        </div>
        <motion.button
          onClick={handleOpenInvite}
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          transition={{ delay: 0.2, duration: 0.3 }}
          className={cn(
            'inline-flex items-center gap-2 px-5 py-2.5 rounded-md text-[15px] font-medium',
            'bg-[#C25E3A] text-white hover:bg-[#D97B5A] transition-all',
            'hover:-translate-y-0.5 hover:shadow-md'
          )}
        >
          <Plus className="w-4 h-4" />
          {t('directory.inviteAgent')}
        </motion.button>
      </motion.div>

      {/* Filter Bar */}
      <motion.div
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        transition={{ delay: 0.2, duration: 0.3 }}
        className="flex flex-col sm:flex-row items-start sm:items-center gap-3 mb-6"
      >
        {/* Status Filter */}
        <div className="flex items-center gap-2">
          <select
            value={statusFilter}
            onChange={(e) => setStatusFilter(e.target.value)}
            className={cn(
              'px-3 py-2 rounded-md bg-[#F7F0E0] border border-[#E3D7BC] text-[13px] text-[#2A2318]',
              'focus:outline-none focus:border-[#C25E3A] focus:ring-[3px] focus:ring-[#C25E3A]/15'
            )}
          >
            <option value="all">{t('directory.filter.all')} ({mariuses.length})</option>
            <option value="online">{t('directory.status.online')} ({mariuses.filter((m) => m.status === 'online').length})</option>
            <option value="working">{t('directory.status.working')} ({mariuses.filter((m) => m.status === 'working').length})</option>
            <option value="idle">{t('directory.status.idle')} ({mariuses.filter((m) => m.status === 'idle').length})</option>
            <option value="offline">{t('directory.status.offline')} ({mariuses.filter((m) => m.status === 'offline').length})</option>
          </select>
        </div>

        {/* Search */}
        <div className="relative flex-1 w-full sm:max-w-xs">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-[#A89880]" />
          <input
            type="text"
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            placeholder={t('directory.searchPlaceholder')}
            className={cn(
              'w-full pl-9 pr-4 py-2 rounded-md bg-[#F7F0E0] border border-[#E3D7BC] text-[15px] text-[#2A2318]',
              'placeholder:text-[#A89880]',
              'focus:outline-none focus:border-[#C25E3A] focus:ring-[3px] focus:ring-[#C25E3A]/15',
              'transition-all'
            )}
          />
        </div>
      </motion.div>

      {/* Agent Cards Grid */}
      {filteredAgents.length === 0 ? (
        <EmptyState
          icon={Users}
          title={t('directory.noAgentsFound')}
          description={
            searchQuery
              ? t('directory.adjustSearch')
              : t('directory.inviteFirst')
          }
          action={
            !searchQuery && (
              <button
                onClick={handleOpenInvite}
                className={cn(
                  'inline-flex items-center gap-2 px-5 py-2.5 rounded-md text-[15px] font-medium',
                  'bg-[#C25E3A] text-white hover:bg-[#D97B5A] transition-all'
                )}
              >
                <Plus className="w-4 h-4" />
                {t('directory.inviteAgent')}
              </button>
            )
          }
        />
      ) : (
        <motion.div
          className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4"
          variants={containerVariants}
          initial="hidden"
          animate="visible"
        >
          {filteredAgents.map((agent) => (
            <AgentCard
              key={agent.id}
              agent={agent}
              onDesignate={handleDesignate}
            />
          ))}
        </motion.div>
      )}

      {/* ─── Invite Agent Modal ─────────────────────────────────────────────── */}
      <Modal
        isOpen={inviteModalOpen}
        onClose={handleCloseInvite}
        title={
          <span className="font-['Fraunces',Georgia,serif] text-[28px] font-semibold text-[#2A2318]">
            <span className="title-initial">{t('directory.inviteAgent').charAt(0)}</span>
            {t('directory.inviteAgent').slice(1)}
          </span>
        }
        maxWidth="max-w-xl"
      >
        <div className="space-y-5">
              {/* Agent Name */}
              <div>
                <label className="block text-[13px] font-medium text-[#2A2318] mb-1">
                  {t('directory.agentName')} <span className="text-[#C25E3A]">*</span>
                </label>
                <input
                  type="text"
                  value={agentName}
                  onChange={(e) => setAgentName(e.target.value)}
                  placeholder={t('directory.agentNamePlaceholder')}
                  className={cn(
                    'w-full px-4 py-2.5 rounded-md bg-[#F7F0E0] border border-[#E3D7BC] text-[15px] text-[#2A2318]',
                    'placeholder:text-[#A89880]',
                    'focus:outline-none focus:border-[#C25E3A] focus:ring-[3px] focus:ring-[#C25E3A]/15',
                    'transition-all'
                  )}
                />
              </div>

              {/* Where this agent will work (FR-007f). Required: the attachment is made once
                  here and never again, so there is no "decide later". */}
              <div>
                <label className="block text-[13px] font-medium text-[#2A2318] mb-1">
                  {t('directory.workplace')} <span className="text-[#C25E3A]">*</span>
                </label>
                {workplacesLoading ? (
                  <p className="text-[13px] text-[#A89880]">{t('directory.workplaceLoading')}</p>
                ) : workplaces.length === 0 ? (
                  // Not an error state — nothing is broken, there is simply nowhere to put an
                  // agent yet. Say what to do about it rather than leaving an empty box.
                  <div className="rounded-md border border-[#E3D7BC] bg-[#F7F0E0] p-3">
                    <p className="text-[13px] text-[#2A2318]">{t('directory.workplaceNone')}</p>
                    <p className="mt-1 text-[11px] text-[#A89880]">
                      {t('directory.workplaceNoneHint')}
                    </p>
                  </div>
                ) : (
                  <select
                    value={workplaceId}
                    onChange={(e) => {
                      setWorkplaceId(e.target.value);
                      // The settings belong to the **workplace**, not to the agent: two
                      // workplaces offer different ones, and a value carried over from the
                      // last pick would be a setting the new one never offered — refused by
                      // the server at the far end of a form the person thought was filled in.
                      setRuntimeOptions({});
                    }}
                    className={cn(
                      'w-full px-4 py-2.5 rounded-md bg-[#F7F0E0] border border-[#E3D7BC] text-[15px] text-[#2A2318]',
                      'focus:outline-none focus:border-[#C25E3A] focus:ring-[3px] focus:ring-[#C25E3A]/15',
                      'transition-all'
                    )}
                  >
                    <option value="">{t('directory.workplacePlaceholder')}</option>
                    {workplaces.map((w) => (
                      <option key={w.id} value={w.id}>
                        {t('directory.workplaceOption', {
                          cliKind: w.cliKind,
                          machineName: w.machineName,
                        })}
                      </option>
                    ))}
                  </select>
                )}
                <p className="mt-1 text-[11px] text-[#A89880]">{t('directory.workplaceHint')}</p>
              </div>

              {/* What this workplace's tool takes, as the tool itself answered it (FR-007k,
                  FR-017). Nothing here is keyed on which CLI it is: the list arrives with the
                  workplace, and a workplace that offered none simply shows nothing. */}
              <RuntimeOptionFields
                options={chosenWorkplace?.options ?? []}
                chosen={runtimeOptions}
                onChange={(key, value) =>
                  setRuntimeOptions((was) => ({ ...was, [key]: value }))
                }
              />

              {/* What the agent is told to be (FR-007i). This is the whole of how it
                  behaves: there is no per-project role adding to it later. */}
              <div>
                <label className="block text-[13px] font-medium text-[#2A2318] mb-1">
                  {t('directory.instructions')}
                </label>
                <textarea
                  value={instructions}
                  onChange={(e) => setInstructions(e.target.value)}
                  rows={5}
                  placeholder={t('directory.instructionsPlaceholder')}
                  className={cn(
                    'w-full px-4 py-2.5 rounded-md bg-[#F7F0E0] border border-[#E3D7BC] text-[15px] text-[#2A2318]',
                    'placeholder:text-[#A89880] resize-y',
                    'focus:outline-none focus:border-[#C25E3A] focus:ring-[3px] focus:ring-[#C25E3A]/15',
                    'transition-all'
                  )}
                />
                <p className="mt-1 text-[11px] text-[#A89880]">{t('directory.instructionsHint')}</p>
              </div>

              {/* What the team calls it. Never sent to the agent (FR-007j). */}
              <div>
                <label className="block text-[13px] font-medium text-[#2A2318] mb-1">
                  {t('directory.agentDescription')}
                </label>
                <input
                  type="text"
                  value={agentDescription}
                  onChange={(e) => setAgentDescription(e.target.value)}
                  placeholder={t('directory.agentDescriptionPlaceholder')}
                  className={cn(
                    'w-full px-4 py-2.5 rounded-md bg-[#F7F0E0] border border-[#E3D7BC] text-[15px] text-[#2A2318]',
                    'placeholder:text-[#A89880]',
                    'focus:outline-none focus:border-[#C25E3A] focus:ring-[3px] focus:ring-[#C25E3A]/15',
                    'transition-all'
                  )}
                />
                <p className="mt-1 text-[11px] text-[#A89880]">
                  {t('directory.agentDescriptionHint')}
                </p>
              </div>

              {/* Workspace Agent seat (#32) */}
              <div>
                <label className="flex items-start gap-2.5 cursor-pointer select-none">
                  <input
                    type="checkbox"
                    checked={makeWorkspaceAgent}
                    onChange={(e) => setMakeWorkspaceAgent(e.target.checked)}
                    className="mt-0.5 w-4 h-4 accent-[#C25E3A]"
                  />
                  <span>
                    <span className="flex items-center gap-1.5 text-[13px] font-medium text-[#2A2318]">
                      <Star className="w-3.5 h-3.5 text-[#D4A843]" />
                      {t('directory.setAsWorkspaceAgent')}
                    </span>
                    <span className="block text-[11px] text-[#A89880]">
                      {t('directory.setAsWorkspaceAgentHint')}
                    </span>
                  </span>
                </label>
                {makeWorkspaceAgent && currentHost && (
                  <p className="mt-2 px-3 py-2 rounded-md bg-[#F5E8CC] text-[12px] text-[#8B6A28]">
                    {t('directory.replaceHostWarning', {
                      name: currentHost.displayName || currentHost.name,
                    })}
                  </p>
                )}
              </div>

              {/* Skills */}
              <div>
                <label className="block text-[13px] font-medium text-[#2A2318] mb-1">
                  {t('directory.skills')}
                </label>
                <div className="flex flex-wrap gap-1.5">
                  {skills.map((skill) => {
                    // A built-in rides every run whether or not anybody picks it, so offering it
                    // as a choice would be offering a switch that is not wired to anything.
                    // Shown as on and not clickable, because it IS on.
                    const always = skill.type === 'builtin';
                    const on = always || selectedSkillIds.includes(skill.id);
                    return (
                      <button
                        key={skill.id}
                        onClick={() => !always && toggleSkill(skill.id)}
                        disabled={always}
                        title={always ? t('directory.skillAlwaysOn') : undefined}
                        className={cn(
                          'inline-flex items-center gap-1 px-3 py-1.5 rounded-full text-[11px] font-medium transition-all',
                          on
                            ? 'bg-[#C25E3A] text-white'
                            : 'bg-[#E3D7BC] text-[#6B5E4E] hover:bg-[#D9CDB8]',
                          always && 'cursor-default opacity-90'
                        )}
                      >
                        {on && (always ? <Lock className="w-3 h-3" /> : <Check className="w-3 h-3" />)}
                        {skill.name}
                      </button>
                    );
                  })}
                </div>
              </div>

              {/* The server's refusal, worded from its own code — a name already taken, a
                  workplace that stopped being able to take work between opening this form
                  and submitting it. Swallowing it would leave the person clicking a button
                  that does nothing and says nothing. */}
              {inviteError && (
                <p className="flex items-start gap-1.5 px-3 py-2 rounded-md bg-[#F3D9D0] text-[12px] text-[#8A3B22] border border-[#E3C0B2]">
                  <AlertTriangle className="w-3.5 h-3.5 flex-shrink-0 mt-0.5" /> {inviteError}
                </p>
              )}

              {/* Footer buttons */}
              <div className="flex justify-end gap-3 pt-2">
                <button
                  onClick={handleCloseInvite}
                  className="px-4 py-2 rounded-md text-[13px] font-medium bg-[#EDE4CE] text-[#2A2318] border border-[#E3D7BC] hover:bg-[#E3D7BC] transition-colors"
                >
                  {t('common.cancel')}
                </button>
                <button
                  onClick={handleInvite}
                  disabled={
                    !agentName.trim() || !workplaceId || sending
                  }
                  className={cn(
                    'inline-flex items-center gap-2 px-4 py-2 rounded-md text-[13px] font-medium transition-all',
                    agentName.trim() && workplaceId && !sending
                      ? 'bg-[#C25E3A] text-white hover:bg-[#D97B5A]'
                      : 'bg-[#E3D7BC] text-[#A89880] cursor-not-allowed'
                  )}
                >
                  {sending && <Loader2 className="w-3.5 h-3.5 animate-spin" />}
                  {sending ? t('directory.send.sending') : t('directory.invite')}
                </button>
              </div>
        </div>
      </Modal>

      {/* Designate (swap) confirmation — the sitting host is demoted, kept (#32) */}
      <ConfirmDialog
        isOpen={designatingAgent !== null}
        onClose={() => setDesignatingAgent(null)}
        onConfirm={async () => {
          if (designatingAgent) await designateWorkspaceAgent(designatingAgent.id);
        }}
        title={t('directory.designateConfirmTitle')}
        message={t('directory.designateConfirmMessage', {
          name: designatingAgent?.displayName || designatingAgent?.name || '',
          current: currentHost?.displayName || currentHost?.name || '',
        })}
        confirmLabel={t('directory.actions.designate')}
      />

      {/* Create-as-host confirmation — creating the agent performs the swap (#32) */}
      <ConfirmDialog
        isOpen={inviteSwapConfirmOpen}
        onClose={() => setInviteSwapConfirmOpen(false)}
        onConfirm={async () => {
          setInviteSwapConfirmOpen(false);
          await doInvite();
        }}
        title={t('directory.designateConfirmTitle')}
        message={t('directory.designateConfirmMessage', {
          name: agentName.trim(),
          current: currentHost?.displayName || currentHost?.name || '',
        })}
        confirmLabel={t('directory.createAndSwap')}
      />
    </div>
  );
}
