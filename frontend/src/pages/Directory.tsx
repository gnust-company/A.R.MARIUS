// @ts-nocheck
import { useState, useMemo, useCallback } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import {
  Users,
  Plus,
  Search,
  Copy,
  Check,
  Star,
  MoreHorizontal,
  ChevronDown,
  ChevronUp,
  X,
  Loader2,
  Bot,
  Clock,
  WifiOff,
  Activity,
  Zap,
  AlertTriangle,
  Settings,
  Code,
  Globe,
  Terminal,
} from 'lucide-react';
import { useMockStore } from '@/store/mockStore';
import type { Marius, AgentStatus } from '@/store/mockStore';
import VellumPanel from '@/components/VellumPanel';
import EmptyState from '@/components/EmptyState';
import Modal from '@/components/Modal';
import PageTitle from '@/components/PageTitle';
import { cn, copyToClipboard } from '@/lib/utils';
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
  hung: { color: '#C25E3A', pulse: false, label: 'Hung', icon: AlertTriangle },
  checking: { color: '#D97B5A', pulse: true, label: 'Checking', icon: Loader2 },
  pending: { color: '#D4A843', pulse: false, label: 'Pending Review', icon: Clock },
  invited: { color: '#A89880', pulse: false, label: 'Invited', icon: Bot },
  revoked: { color: '#8B7A6A', pulse: false, label: 'Revoked', icon: WifiOff },
};

// ─── Adapter Options ─────────────────────────────────────────────────────────

const ADAPTER_OPTIONS = [
  { value: 'hermes_gateway', label: 'Hermes Gateway', desc: 'External gateway with full protocol support', icon: Globe },
  { value: 'openclaw_gateway', label: 'OpenClaw Gateway', desc: 'Open-source adapter for custom integrations', icon: Settings },
  { value: 'claude_local', label: 'Claude Code (Local)', desc: 'Local Claude Code execution environment', icon: Code },
  { value: 'echo', label: 'Echo', desc: 'Simple echo adapter for testing', icon: Terminal },
];

const ROLE_OPTIONS = [
  'Project Leader',
  'Frontend Developer',
  'Backend Developer',
  'Designer',
  'QA Engineer',
];

// Maps a stored (English) role value → its i18n key. The <option> value stays
// English (it is persisted on the agent); only the visible label is translated.
const ROLE_KEY: Record<string, string> = {
  'Project Leader': 'projectLeader',
  'Frontend Developer': 'frontendDeveloper',
  'Backend Developer': 'backendDeveloper',
  'Designer': 'designer',
  'QA Engineer': 'qaEngineer',
};

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
  onApprove,
  onDesignate,
}: {
  agent: Marius;
  onApprove: (id: string) => void;
  onDesignate: (id: string) => void;
}) {
  const { t } = useTranslation();
  const config = STATUS_CONFIG[agent.status] || STATUS_CONFIG.offline;
  const [expanded, setExpanded] = useState(false);
  const [approving, setApproving] = useState(false);
  const [menuOpen, setMenuOpen] = useState(false);

  const handleApprove = () => {
    setApproving(true);
    setTimeout(() => {
      onApprove(agent.id);
      setApproving(false);
    }, 400);
  };

  const StatusIcon = config.icon;
  const displayName = agent.displayName || agent.name;
  const agentSkills = agent.skills || [];

  return (
    <motion.div variants={cardVariants} layout>
      <VellumPanel className="relative h-full">
        {/* Top row: status dot + avatar + name + WA badge + menu */}
        <div className="flex items-start gap-3">
          <div className="flex items-center gap-2 flex-shrink-0 mt-1">
            <StatusDot status={agent.status} />
          </div>

          {/* Avatar */}
          <div
            className="w-10 h-10 rounded-full overflow-hidden flex-shrink-0 border-2"
            style={{ borderColor: config.color }}
          >
            {agent.avatar ? (
              <img
                src={agent.avatar}
                alt={displayName}
                className="w-full h-full object-cover"
              />
            ) : (
              <Bot className="w-5 h-5 m-2.5 text-ink-muted" />
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
                  <Star className="w-3 h-3" /> WA
                </span>
              )}
            </div>
            <div className="flex items-center gap-2 mt-1">
              <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[11px] font-medium bg-[#E3D7BC] text-[#6B5E4E]">
                {agent.role}
              </span>
              <span
                className="inline-flex items-center gap-1 text-[11px] font-medium"
                style={{ color: config.color }}
              >
                <StatusIcon className="w-3 h-3" />
                {t('directory.status.' + agent.status)}
              </span>
            </div>
          </div>

          {/* Menu button */}
          <div className="relative">
            <button
              onClick={() => setMenuOpen(!menuOpen)}
              className="p-1.5 rounded-md text-ink-muted hover:text-ink hover:bg-[#EDE4CE] transition-colors"
            >
              <MoreHorizontal className="w-4 h-4" />
            </button>
            <AnimatePresence>
              {menuOpen && (
                <>
                  <div className="fixed inset-0 z-10" onClick={() => setMenuOpen(false)} />
                  <motion.div
                    initial={{ opacity: 0, scale: 0.95, y: -4 }}
                    animate={{ opacity: 1, scale: 1, y: 0 }}
                    exit={{ opacity: 0, scale: 0.95, y: -4 }}
                    transition={{ duration: 0.15 }}
                    className="absolute right-0 top-full mt-1 w-48 bg-[#F7F0E0] border border-[#E3D7BC] rounded-lg shadow-lg z-20 py-1"
                  >
                    <button
                      onClick={() => { setExpanded(!expanded); setMenuOpen(false); }}
                      className="w-full text-left px-3 py-2 text-[13px] text-[#2A2318] hover:bg-[#EDE4CE] transition-colors"
                    >
                      {expanded ? t('directory.collapseDetails') : t('directory.viewDetails')}
                    </button>
                    {agent.status === 'online' && agent.isWorkspaceAgent !== true && (
                      <button
                        onClick={() => { onDesignate(agent.id); setMenuOpen(false); }}
                        className="w-full text-left px-3 py-2 text-[13px] text-[#D4A843] hover:bg-[#EDE4CE] transition-colors"
                      >
                        <span className="flex items-center gap-1.5">
                          <Star className="w-3.5 h-3.5" /> {t('directory.actions.designate')}
                        </span>
                      </button>
                    )}
                  </motion.div>
                </>
              )}
            </AnimatePresence>
          </div>
        </div>

        {/* Metadata */}
        <div className="mt-3 flex items-center gap-2 text-[12px] font-mono text-[#6B5E4E]">
          <span>{agent.adapterType || '—'}</span>
          <span className="text-[#A89880]">&middot;</span>
          <span className="text-[#A89880]">
            {agent.status ? t('directory.statusLabel', { status: t('directory.status.' + agent.status) }) : t('directory.unknownStatus')}
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
          {agent.status === 'pending' && (
            <>
              <button
                onClick={handleApprove}
                disabled={approving}
                className={cn(
                  'inline-flex items-center gap-1.5 px-4 py-2 rounded-md text-[13px] font-medium transition-all',
                  'bg-[#C25E3A] text-white hover:bg-[#D97B5A] disabled:opacity-50'
                )}
              >
                {approving ? (
                  <Loader2 className="w-3.5 h-3.5 animate-spin" />
                ) : (
                  <Check className="w-3.5 h-3.5" />
                )}
                {t('directory.actions.approve')}
              </button>
              <button
                onClick={() => onApprove(agent.id)}
                className="inline-flex items-center gap-1.5 px-4 py-2 rounded-md text-[13px] font-medium border border-[#E3D7BC] text-[#6B5E4E] hover:bg-[#F5DDD6] hover:text-[#8B3A28] hover:border-[#E8B8A8] transition-all"
              >
                <X className="w-3.5 h-3.5" />
                {t('directory.reject')}
              </button>
            </>
          )}
          {agent.status === 'invited' && (
            <span className="inline-flex items-center gap-1.5 px-4 py-2 rounded-md text-[13px] font-medium text-[#A89880]">
              <Clock className="w-3.5 h-3.5" />
              {t('directory.waitingEnrollment')}
            </span>
          )}
          {agent.status === 'online' && agent.isWorkspaceAgent !== true && (
            <button
              onClick={() => onDesignate(agent.id)}
              className="inline-flex items-center gap-1.5 px-4 py-2 rounded-md text-[13px] font-medium border border-[#D4A843] text-[#D4A843] hover:bg-[#D4A843] hover:text-[#2A2318] transition-all"
            >
              <Star className="w-3.5 h-3.5" />
              {t('directory.actions.designate')}
            </button>
          )}
          {agent.isWorkspaceAgent === true && (
            <span className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-md text-[11px] font-medium bg-[#F5E8CC] text-[#8B6A28]">
              <Star className="w-3 h-3" /> {t('directory.workspaceAgent')}
            </span>
          )}
        </div>

        {/* Expanded details */}
        <AnimatePresence>
          {expanded && (
            <motion.div
              initial={{ height: 0, opacity: 0 }}
              animate={{ height: 'auto', opacity: 1 }}
              exit={{ height: 0, opacity: 0 }}
              transition={{ duration: 0.2 }}
              className="overflow-hidden"
            >
              <div className="mt-4 pt-4 border-t border-[#E3D7BC]">
                <div className="text-[12px] font-mono text-[#6B5E4E] space-y-1">
                  <p>
                    <span className="text-[#A89880]">{t('directory.details.id')}:</span> {agent.id}
                  </p>
                  <p>
                    <span className="text-[#A89880]">{t('directory.details.role')}:</span> {agent.role}
                  </p>
                  <p>
                    <span className="text-[#A89880]">{t('directory.details.adapter')}:</span> {agent.adapterType || '—'}
                  </p>
                  <p>
                    <span className="text-[#A89880]">{t('directory.details.workspace')}:</span> {agent.workspaceId}
                  </p>
                </div>
              </div>
            </motion.div>
          )}
        </AnimatePresence>
      </VellumPanel>
    </motion.div>
  );
}

// ═══════════════════════════════════════════════════════════════════════════════
// MAIN PAGE: Directory
// ═══════════════════════════════════════════════════════════════════════════════

export default function Directory() {
  const { t } = useTranslation();
  const mariuses = useMockStore((s) => s.mariuses);
  const skills = useMockStore((s) => s.skills);
  const inviteAgent = useMockStore((s) => s.inviteAgent);
  const approveAgent = useMockStore((s) => s.approveAgent);
  const emitEvent = useMockStore((s) => s.emitEvent);

  // ── Filter State ───────────────────────────────────────────────────────────
  const [searchQuery, setSearchQuery] = useState('');
  const [statusFilter, setStatusFilter] = useState<string>('all');
  const [showPendingOnly, setShowPendingOnly] = useState(false);

  // ── Invite Modal State ─────────────────────────────────────────────────────
  const [inviteModalOpen, setInviteModalOpen] = useState(false);
  const [inviteStep, setInviteStep] = useState<'form' | 'prompt'>('form');
  const [adapterType, setAdapterType] = useState('hermes_gateway');
  const [agentName, setAgentName] = useState('');
  const [agentRole, setAgentRole] = useState('');
  const [customRole, setCustomRole] = useState('');
  const [selectedSkillIds, setSelectedSkillIds] = useState<string[]>([]);
  const [generating, setGenerating] = useState(false);
  const [enrollmentCode, setEnrollmentCode] = useState('');
  const [_invitedAgentId, setInvitedAgentId] = useState('');
  const [copied, setCopied] = useState(false);
  const [copyFailed, setCopyFailed] = useState(false);

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
        if (m.status === 'pending') return 0;
        return -1;
      };
      return score(b) - score(a) || (a.displayName || a.name).localeCompare(b.displayName || b.name);
    });

    return filtered;
  }, [mariuses, searchQuery, statusFilter]);

  const pendingAgents = useMemo(
    () => mariuses.filter((m) => m.status === 'pending' || m.status === 'invited'),
    [mariuses]
  );

  // ── Handlers ───────────────────────────────────────────────────────────────
  const handleOpenInvite = () => {
    setInviteStep('form');
    setAdapterType('hermes_gateway');
    setAgentName('');
    setAgentRole('');
    setCustomRole('');
    setSelectedSkillIds([]);
    setEnrollmentCode('');
    setInvitedAgentId('');
    setCopied(false);
    setInviteModalOpen(true);
  };

  const handleGenerateInvite = () => {
    if (!agentName.trim() || (!agentRole && !customRole.trim())) return;
    setGenerating(true);
    setTimeout(() => {
      const role = agentRole === 'Custom...' ? customRole : agentRole;
      const code = `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`;

      // Create agent directly since inviteAgent expects (mariusId, workspaceId)
      const newAgentId = `m-${Date.now().toString(36)}`;
      const state = useMockStore.getState();
      const newAgent = {
        id: newAgentId,
        name: agentName.trim().toLowerCase().replace(/\s+/g, '-'),
        displayName: agentName.trim(),
        adapterType,
        role,
        roleKey: role.toLowerCase().replace(/\s+/g, '_'),
        skills: selectedSkillIds,
        avatar: '/agent-avatar-echo.jpg',
        status: 'invited' as AgentStatus,
        workspaceId: state.activeWorkspaceId || 'w1',
        projectIds: [],
        description: `Invited \u2014 ${role}`,
        isWorkspaceAgent: false,
      };

      useMockStore.setState({
        mariuses: [...state.mariuses, newAgent],
      });

      // Also call inviteAgent for side effects if the store has logic for it
      try {
        inviteAgent(newAgentId, state.activeWorkspaceId || 'w1');
      } catch {
        // inviteAgent may not accept these args, agent already added above
      }

      setEnrollmentCode(code);
      setInvitedAgentId(newAgent.id);
      setGenerating(false);
      setInviteStep('prompt');

      // Simulate auto-transition to pending after 3s
      setTimeout(() => {
        const store = useMockStore.getState();
        const currentAgent = store.mariuses.find((m) => m.id === newAgentId);
        if (currentAgent && currentAgent.status === 'invited') {
          useMockStore.setState({
            mariuses: store.mariuses.map((m) =>
              m.id === newAgentId ? { ...m, status: 'pending' as AgentStatus } : m
            ),
          });
          store.emitEvent({
            type: 'marius.status_changed',
            payload: { mariusId: newAgentId, from: 'invited', to: 'pending' },
          });
        }
      }, 3000);
    }, 600);
  };

  const handleCopyPrompt = () => {
    const promptText = [
      `You are being invited to join the workspace as a ${agentRole === 'Custom...' ? customRole : agentRole}.`,
      '',
      `API Base: /v1`,
      `Enrollment Code: ${enrollmentCode}`,
      '',
      selectedSkillIds.length > 0
        ? `Skills to install:\n${selectedSkillIds.map((sid) => {
            const sk = skills.find((s) => s.id === sid || s.name === sid);
            return `  - ${sk?.name || sid}`;
          }).join('\n')}`
        : '',
      '',
      'To join, call POST /agent/enroll with your enrollment_code and wait for approval.',
    ].join('\n');
    void copyToClipboard(promptText).then((ok) => {
      if (ok) {
        setCopyFailed(false);
        setCopied(true);
        setTimeout(() => setCopied(false), 2000);
      } else {
        setCopied(false);
        setCopyFailed(true);
        setTimeout(() => setCopyFailed(false), 4000);
      }
    });
  };

  const handleApprove = useCallback(
    (id: string) => {
      approveAgent(id);
      emitEvent({
        type: 'marius.online',
        payload: { mariusId: id },
      });
    },
    [approveAgent, emitEvent]
  );

  const handleDesignate = useCallback(
    (id: string) => {
      // First remove WA from any existing agent
      const state = useMockStore.getState();
      const updatedMariuses = state.mariuses.map((m) => ({
        ...m,
        isWorkspaceAgent: m.id === id ? true : false,
      }));
      useMockStore.setState({ mariuses: updatedMariuses });
      emitEvent({
        type: 'workspace_agent.designated',
        payload: { mariusId: id },
      });
    },
    [emitEvent]
  );

  const handleCloseInvite = () => {
    setInviteModalOpen(false);
    setInviteStep('form');
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
            <option value="pending">{t('directory.status.pending')} ({mariuses.filter((m) => m.status === 'pending').length})</option>
            <option value="invited">{t('directory.status.invited')} ({mariuses.filter((m) => m.status === 'invited').length})</option>
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

        {/* Pending toggle */}
        {pendingAgents.length > 0 && (
          <button
            onClick={() => setShowPendingOnly(!showPendingOnly)}
            className={cn(
              'inline-flex items-center gap-1.5 px-3 py-2 rounded-md text-[13px] font-medium transition-colors',
              showPendingOnly
                ? 'bg-[#C25E3A] text-white'
                : 'bg-[#F7F0E0] border border-[#E3D7BC] text-[#6B5E4E] hover:bg-[#EDE4CE]'
            )}
          >
            <Clock className="w-3.5 h-3.5" />
            {t('directory.pending')} ({pendingAgents.length})
            {showPendingOnly ? <ChevronUp className="w-3.5 h-3.5" /> : <ChevronDown className="w-3.5 h-3.5" />}
          </button>
        )}
      </motion.div>

      {/* Pending Agents Section */}
      {showPendingOnly && pendingAgents.length > 0 && (
        <motion.div
          initial={{ height: 0, opacity: 0 }}
          animate={{ height: 'auto', opacity: 1 }}
          exit={{ height: 0, opacity: 0 }}
          className="mb-6"
        >
          <h2 className="text-[13px] font-medium text-[#A89880] uppercase tracking-wider mb-3">
            {t('directory.pendingInvites')}
          </h2>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            {pendingAgents.map((agent) => (
              <AgentCard
                key={agent.id}
                agent={agent}
                onApprove={handleApprove}
                onDesignate={handleDesignate}
              />
            ))}
          </div>
        </motion.div>
      )}

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
              onApprove={handleApprove}
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
          (() => {
            const full = inviteStep === 'form' ? t('directory.inviteAgent') : t('directory.invitePrompt');
            return (
              <span className="font-['Fraunces',Georgia,serif] text-[28px] font-semibold text-[#2A2318]">
                <span className="title-initial">{full.charAt(0)}</span>
                {full.slice(1)}
              </span>
            );
          })()
        }
        maxWidth="max-w-xl"
      >
        <AnimatePresence mode="wait">
          {inviteStep === 'form' ? (
            <motion.div
              key="form"
              initial={{ opacity: 0, x: -10 }}
              animate={{ opacity: 1, x: 0 }}
              exit={{ opacity: 0, x: 10 }}
              transition={{ duration: 0.2 }}
              className="space-y-5"
            >
              {/* Adapter Type */}
              <div>
                <label className="block text-[13px] font-medium text-[#2A2318] mb-2">
                  {t('directory.adapterType')} <span className="text-[#C25E3A]">*</span>
                </label>
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
                  {ADAPTER_OPTIONS.map((opt) => {
                    const Icon = opt.icon;
                    const selected = adapterType === opt.value;
                    return (
                      <button
                        key={opt.value}
                        onClick={() => setAdapterType(opt.value)}
                        className={cn(
                          'flex items-start gap-3 p-3 rounded-md border text-left transition-all',
                          selected
                            ? 'border-[#C25E3A] bg-[#C25E3A]/5'
                            : 'border-[#E3D7BC] hover:bg-[#EDE4CE]'
                        )}
                      >
                        <Icon
                          className={cn(
                            'w-5 h-5 flex-shrink-0 mt-0.5',
                            selected ? 'text-[#C25E3A]' : 'text-[#6B5E4E]'
                          )}
                        />
                        <div>
                          <p
                            className={cn(
                              'text-[13px] font-medium',
                              selected ? 'text-[#C25E3A]' : 'text-[#2A2318]'
                            )}
                          >
                            {t('directory.adapters.' + opt.value + '.label')}
                          </p>
                          <p className="text-[11px] text-[#A89880]">{t('directory.adapters.' + opt.value + '.desc')}</p>
                        </div>
                      </button>
                    );
                  })}
                </div>
              </div>

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

              {/* Role */}
              <div>
                <label className="block text-[13px] font-medium text-[#2A2318] mb-1">
                  {t('directory.role')} <span className="text-[#C25E3A]">*</span>
                </label>
                <select
                  value={agentRole}
                  onChange={(e) => setAgentRole(e.target.value)}
                  className={cn(
                    'w-full px-4 py-2.5 rounded-md bg-[#F7F0E0] border border-[#E3D7BC] text-[15px] text-[#2A2318]',
                    'focus:outline-none focus:border-[#C25E3A] focus:ring-[3px] focus:ring-[#C25E3A]/15',
                    'transition-all'
                  )}
                >
                  <option value="">{t('directory.selectRole')}</option>
                  {ROLE_OPTIONS.map((r) => (
                    <option key={r} value={r}>
                      {t('directory.roles.' + ROLE_KEY[r])}
                    </option>
                  ))}
                  <option value="Custom...">{t('directory.custom')}</option>
                </select>
                {agentRole === 'Custom...' && (
                  <motion.input
                    initial={{ height: 0, opacity: 0 }}
                    animate={{ height: 'auto', opacity: 1 }}
                    type="text"
                    value={customRole}
                    onChange={(e) => setCustomRole(e.target.value)}
                    placeholder={t('directory.customRolePlaceholder')}
                    className={cn(
                      'w-full mt-2 px-4 py-2.5 rounded-md bg-[#F7F0E0] border border-[#E3D7BC] text-[15px] text-[#2A2318]',
                      'placeholder:text-[#A89880]',
                      'focus:outline-none focus:border-[#C25E3A] focus:ring-[3px] focus:ring-[#C25E3A]/15',
                      'transition-all'
                    )}
                  />
                )}
              </div>

              {/* Skills */}
              <div>
                <label className="block text-[13px] font-medium text-[#2A2318] mb-1">
                  {t('directory.skills')}
                </label>
                <div className="flex flex-wrap gap-1.5">
                  {skills.map((skill) => (
                    <button
                      key={skill.id}
                      onClick={() => toggleSkill(skill.name)}
                      className={cn(
                        'inline-flex items-center gap-1 px-3 py-1.5 rounded-full text-[11px] font-medium transition-all',
                        selectedSkillIds.includes(skill.name)
                          ? 'bg-[#C25E3A] text-white'
                          : 'bg-[#E3D7BC] text-[#6B5E4E] hover:bg-[#D9CDB8]'
                      )}
                    >
                      {selectedSkillIds.includes(skill.name) && (
                        <Check className="w-3 h-3" />
                      )}
                      {skill.name}
                    </button>
                  ))}
                </div>
              </div>

              {/* Footer buttons */}
              <div className="flex justify-end gap-3 pt-2">
                <button
                  onClick={handleCloseInvite}
                  className="px-4 py-2 rounded-md text-[13px] font-medium bg-[#EDE4CE] text-[#2A2318] border border-[#E3D7BC] hover:bg-[#E3D7BC] transition-colors"
                >
                  {t('common.cancel')}
                </button>
                <button
                  onClick={handleGenerateInvite}
                  disabled={
                    !agentName.trim() ||
                    (!agentRole && !customRole.trim()) ||
                    (agentRole === 'Custom...' && !customRole.trim()) ||
                    generating
                  }
                  className={cn(
                    'inline-flex items-center gap-2 px-4 py-2 rounded-md text-[13px] font-medium transition-all',
                    agentName.trim() && (agentRole || customRole.trim()) && !generating
                      ? 'bg-[#C25E3A] text-white hover:bg-[#D97B5A]'
                      : 'bg-[#E3D7BC] text-[#A89880] cursor-not-allowed'
                  )}
                >
                  {generating && <Loader2 className="w-3.5 h-3.5 animate-spin" />}
                  {t('directory.generateInvite')}
                </button>
              </div>
            </motion.div>
          ) : (
            <motion.div
              key="prompt"
              initial={{ opacity: 0, x: 10 }}
              animate={{ opacity: 1, x: 0 }}
              exit={{ opacity: 0, x: -10 }}
              transition={{ duration: 0.2 }}
              className="space-y-4"
            >
              {/* Prompt display */}
              <div className="bg-[#F7F0E0] border border-[#E3D7BC] rounded-md p-4 font-mono text-[13px] text-[#2A2318] whitespace-pre-wrap leading-relaxed max-h-80 overflow-y-auto">
                You are being invited to join the workspace as a{' '}
                <strong>{agentRole === 'Custom...' ? customRole : agentRole}</strong>.
                {'\n\n'}
                API Base: /v1{'\n'}
                Enrollment Code:{' '}
                <span className="text-[#C25E3A] font-semibold">{enrollmentCode}</span>
                {'\n\n'}
                {selectedSkillIds.length > 0 && (
                  <>
                    Skills to install:{'\n'}
                    {selectedSkillIds.map((sid) => {
                      const sk = skills.find((s) => s.id === sid || s.name === sid);
                      return `  - ${sk?.name || sid}\n`;
                    }).join('')}
                    {'\n'}
                  </>
                )}
                To join, call POST /agent/enroll with your enrollment_code and wait for approval.
              </div>

              {/* Actions */}
              <div className="flex justify-end gap-3">
                <button
                  onClick={handleCopyPrompt}
                  className={cn(
                    'inline-flex items-center gap-2 px-4 py-2 rounded-md text-[13px] font-medium transition-all',
                    copied
                      ? 'bg-[#D8EADD] text-[#2A6E3A]'
                      : copyFailed
                        ? 'bg-[#F3D9D0] text-[#8A3B22] border border-[#E3C0B2]'
                        : 'bg-[#EDE4CE] text-[#2A2318] border border-[#E3D7BC] hover:bg-[#E3D7BC]'
                  )}
                >
                  {copied ? (
                    <>
                      <Check className="w-3.5 h-3.5" /> {t('directory.copied')}
                    </>
                  ) : copyFailed ? (
                    <>
                      <Copy className="w-3.5 h-3.5" /> {t('directory.copyFailed')}
                    </>
                  ) : (
                    <>
                      <Copy className="w-3.5 h-3.5" /> {t('directory.copyClipboard')}
                    </>
                  )}
                </button>
                <button
                  onClick={handleCloseInvite}
                  className="px-4 py-2 rounded-md text-[13px] font-medium bg-[#C25E3A] text-white hover:bg-[#D97B5A] transition-colors"
                >
                  {t('directory.done')}
                </button>
              </div>
            </motion.div>
          )}
        </AnimatePresence>
      </Modal>
    </div>
  );
}
