// Single-agent detail view (#72). Opened by clicking an agent card in the Directory. The
// right column is the system↔agent interaction log the owner tracks: every Run the system
// dispatched to this agent (assignment, mention, comment, …), each expandable to its
// durable per-run trace (RunEvent). Data is read-only, and a live run advances in place off
// the workspace event channel — no timer (T167, FR-080).
import { useEffect, useState, useCallback } from 'react';
import { useParams, useNavigate } from 'react-router';
import { useTranslation } from 'react-i18next';
import { motion } from 'framer-motion';
import {
  ChevronLeft,
  ChevronDown,
  ChevronUp,
  Bot,
  Star,
  Activity,
  Loader2,
  Globe,
  Code,
  Terminal,
  Settings,
  Clock,
  Wrench,
  MessageSquare,
  AlertTriangle,
  Check,
  CheckCircle2,
  Plus,
} from 'lucide-react';
import { useAppStore } from '@/store/appStore';
import type { AgentStatus } from '@/store/appStore';
import { listMariusRuns, listRunEvents, type RunDTO, type RunEventDTO } from '@/lib/api';
import Modal from '@/components/Modal';
import VellumPanel from '@/components/VellumPanel';
import { cn, wsHref } from '@/lib/utils';
import { errorText } from '@/lib/errors';
import { onWorkspaceEvent } from '@/hooks/use-workspace-events';

// ─── Status palette (mirrors Directory's Scriptorium tones) ───────────────────

const STATUS_COLORS: Record<AgentStatus, { color: string; label: string }> = {
  online: { color: '#4A9E6B', label: 'online' },
  working: { color: '#D4A843', label: 'working' },
  idle: { color: '#A89880', label: 'idle' },
  offline: { color: '#8B7A6A', label: 'offline' },
  pending: { color: '#D4A843', label: 'pending' },
  invited: { color: '#A89880', label: 'invited' },
  revoked: { color: '#8B7A6A', label: 'revoked' },
};

// Run lifecycle → chip tone. Terminal-good greens, in-flight golds, failures terracotta.
const RUN_STATUS_COLORS: Record<string, { bg: string; text: string }> = {
  queued: { bg: 'bg-[#EDE4CE]', text: 'text-[#6B5E4E]' },
  running: { bg: 'bg-[#F5E8CC]', text: 'text-[#8B6A28]' },
  completed: { bg: 'bg-[#D8EADD]', text: 'text-[#2A6E3A]' },
  failed: { bg: 'bg-[#F3D9D0]', text: 'text-[#8A3B22]' },
  timed_out: { bg: 'bg-[#F3D9D0]', text: 'text-[#8A3B22]' },
  stopped: { bg: 'bg-[#E8E0D8]', text: 'text-[#8B7A6A]' },
};

const ADAPTER_ICON: Record<string, typeof Globe> = {
  openclaw_gateway: Settings,
  claude_local: Code,
  echo: Terminal,
};

// ─── Time helpers ─────────────────────────────────────────────────────────────

function useRelativeTime() {
  const { i18n } = useTranslation();
  return useCallback(
    (iso?: string | null): string => {
      if (!iso) return '—';
      const rtf = new Intl.RelativeTimeFormat(i18n.language || 'en', { numeric: 'auto' });
      const diff = (new Date(iso).getTime() - Date.now()) / 1000;
      const abs = Math.abs(diff);
      if (abs < 60) return rtf.format(Math.round(diff), 'second');
      if (abs < 3600) return rtf.format(Math.round(diff / 60), 'minute');
      if (abs < 86400) return rtf.format(Math.round(diff / 3600), 'hour');
      return rtf.format(Math.round(diff / 86400), 'day');
    },
    [i18n.language]
  );
}

function formatAbsolute(iso?: string | null): string {
  if (!iso) return '—';
  return new Date(iso).toLocaleString();
}

// ─── Field row (label · value) ────────────────────────────────────────────────

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <p className="text-[11px] font-medium uppercase tracking-[0.12em] text-[#A89880]">{label}</p>
      <div className="mt-0.5 text-[13px] text-[#2A2318] break-words">{children}</div>
    </div>
  );
}

// ─── Run event row (the durable per-run trace) ────────────────────────────────

function eventText(ev: RunEventDTO): string {
  const p = ev.payload || {};
  return String(p.content ?? p.delta ?? p.text ?? p.tool_name ?? p.message ?? '');
}

function RunEventList({ runId }: { runId: string }) {
  const { t } = useTranslation();
  const [events, setEvents] = useState<RunEventDTO[] | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    // `loading` starts true and this component remounts per run (keyed by expand), so no
    // need to reset it here — that would only trip the set-state-in-effect lint for nothing.
    let alive = true;
    listRunEvents(runId)
      .then((rows) => { if (alive) setEvents(rows); })
      .catch(() => { if (alive) setEvents([]); })
      .finally(() => { if (alive) setLoading(false); });
    return () => { alive = false; };
  }, [runId]);

  if (loading) {
    return (
      <div className="flex items-center gap-2 px-3 py-3 text-[12px] text-[#A89880]">
        <Loader2 className="w-3.5 h-3.5 animate-spin" /> {t('agentDetail.loadingTrace')}
      </div>
    );
  }
  if (!events || events.length === 0) {
    return <div className="px-3 py-3 text-[12px] text-[#A89880]">{t('agentDetail.noTrace')}</div>;
  }
  return (
    <div className="space-y-1.5 px-1 py-2">
      {events.map((ev) => {
        const isTool = ev.type.includes('tool');
        const Icon = isTool ? Wrench : MessageSquare;
        const text = eventText(ev);
        return (
          <div key={ev.seq} className="flex gap-2 px-2 py-1.5 rounded bg-[#F7F0E0] border border-[#EDE4CE]">
            <Icon className="w-3.5 h-3.5 mt-0.5 flex-shrink-0 text-[#A89880]" />
            <div className="min-w-0">
              <span className="text-[11px] font-mono text-[#8B7A6A]">{ev.type}</span>
              {text && <p className="text-[12px] text-[#2A2318] break-words whitespace-pre-wrap">{text}</p>}
            </div>
          </div>
        );
      })}
    </div>
  );
}

// ─── Run card (one system→agent dispatch) ─────────────────────────────────────

function RunRow({ run }: { run: RunDTO }) {
  const { t } = useTranslation();
  const rel = useRelativeTime();
  const [open, setOpen] = useState(false);
  const tone = RUN_STATUS_COLORS[run.status] || RUN_STATUS_COLORS.stopped;
  const wakeLabel = t(`agentDetail.wakeSource.${run.wake_source}`, { defaultValue: run.wake_source });
  const statusLabel = t(`agentDetail.runStatus.${run.status}`, { defaultValue: run.status });
  // Every cause, worded here rather than on the server: the same wake also went to an
  // agent, and that copy is always English (Hiến pháp VII), so the server stores the code
  // and both sides render it. A run recorded before the codes existed has no causes —
  // it falls back to the sentence it does carry.
  const wakeReason = (run.trigger_causes ?? []).length
    ? (run.trigger_causes ?? [])
        .map((c) => t(`agentDetail.wakeReason.${c.code}`, { ...(c.params ?? {}), defaultValue: c.code }))
        .join(' · ')
    : run.trigger_detail;

  return (
    <div className="rounded-lg border border-[#E3D7BC] bg-[#FBF6EA] overflow-hidden">
      <button
        onClick={() => setOpen((v) => !v)}
        className="w-full flex items-start gap-3 px-4 py-3 text-left hover:bg-[#F3ECDA] transition-colors"
      >
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <span className="text-[13px] font-medium text-[#2A2318]">{wakeLabel}</span>
            <span className={cn('inline-flex items-center rounded-full px-2 py-0.5 text-[11px] font-medium', tone.bg, tone.text)}>
              {statusLabel}
            </span>
          </div>
          {wakeReason && (
            <p className="mt-1 text-[12px] text-[#6B5E4E] break-words line-clamp-2">{wakeReason}</p>
          )}
          {run.error && (
            <p className="mt-1 flex items-start gap-1 text-[12px] text-[#8A3B22]">
              <AlertTriangle className="w-3.5 h-3.5 mt-0.5 flex-shrink-0" /> {run.error}
            </p>
          )}
          {run.next_action && (
            <p className="mt-1 text-[12px] text-[#6B5E4E] break-words">
              <span className="text-[#A89880]">{t('agentDetail.nextAction')}: </span>{run.next_action}
            </p>
          )}
          <p className="mt-1 text-[11px] text-[#A89880]" title={formatAbsolute(run.created_at)}>
            {rel(run.created_at)}
          </p>
        </div>
        {open ? <ChevronUp className="w-4 h-4 text-[#A89880] mt-1" /> : <ChevronDown className="w-4 h-4 text-[#A89880] mt-1" />}
      </button>
      {open && (
        <div className="border-t border-[#E3D7BC] bg-[#F7F0E0]/60">
          <RunEventList runId={run.id} />
        </div>
      )}
    </div>
  );
}

// ═══════════════════════════════════════════════════════════════════════════════
// PAGE
// ═══════════════════════════════════════════════════════════════════════════════

export default function AgentDetail() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const rel = useRelativeTime();
  const { workspaceId, id } = useParams();
  const mariuses = useAppStore((s) => s.mariuses);
  const allSkills = useAppStore((s) => s.skills);
  const installAgentSkills = useAppStore((s) => s.installAgentSkills);
  const agent = mariuses.find((m) => m.id === id);

  const [runs, setRuns] = useState<RunDTO[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  // Linking skills to an agent (#74). Nothing is pushed at the agent: a skill travels down
  // with the work that needs it (FR-011b), so linking is the whole of the act. The agent
  // confirms each install out of band (POST /agent/skills/{slug}/installed), flipping the
  // per-skill badge pending → installed. State is carried on agent.skillInstalls.
  const [linkSkillsOpen, setLinkSkillsOpen] = useState(false);
  const [selectedNewIds, setSelectedNewIds] = useState<string[]>([]);
  const [installing, setInstalling] = useState(false);
  const [linkFailed, setLinkFailed] = useState(false);
  const [linked, setLinked] = useState(false);

  // Push, not poll (Constitution IV, FR-080). This screen watches an *agent*, and until
  // T167 no channel spoke about agents — so it re-asked the server every fifteen seconds,
  // forever, whether or not the agent had done anything. The server now announces each run
  // lifecycle change on the workspace channel, which is the connection `Layout` already
  // holds open, so listening costs nothing extra.
  //
  // The event is a **signal**, not the data: on receipt this re-reads the run list rather
  // than trying to patch a row out of the payload (contracts/push-events.md, principle 1).
  const loadRuns = useCallback(() => {
    if (!workspaceId || !id) return;
    listMariusRuns(workspaceId, id)
      .then((rows) => { setRuns(rows); setError(null); })
      .catch((e) => setError(errorText(e, t)));
  }, [workspaceId, id, t]);

  useEffect(() => { loadRuns(); }, [loadRuns]);

  // One re-read per burst, not one per event. A single run announces itself three times
  // (opened, started, finished) and several runs can land together, so reacting to each
  // event separately would fire more requests in a busy moment than the 15s timer this
  // replaced. Coalescing keeps the screen honest — the last event in a burst still wins,
  // because the re-read happens after it.
  useEffect(() => {
    if (!workspaceId || !id) return;
    let pending: ReturnType<typeof setTimeout> | null = null;
    const unsubscribe = onWorkspaceEvent((event) => {
      if (event.type !== 'run.status_changed') return;
      // The channel carries every agent in the workspace; only this one's runs are on screen.
      if (event.payload.marius_id !== id) return;
      if (pending) return;
      pending = setTimeout(() => { pending = null; loadRuns(); }, 300);
    });
    return () => {
      if (pending) clearTimeout(pending);
      unsubscribe();
    };
  }, [workspaceId, id, loadRuns]);

  const status: AgentStatus = agent?.status || 'offline';
  const statusColor = STATUS_COLORS[status] || STATUS_COLORS.offline;
  const displayName = agent?.displayName || agent?.name || t('agentDetail.agentFallback');
  const AdapterIcon = ADAPTER_ICON[agent?.adapterType || ''] || Globe;
  const linkedSkillNames = agent?.skills || [];

  // Per-skill install state (#74) is keyed by slug; the linked pills show it by name.
  const skillInstalls = agent?.skillInstalls ?? {};
  const slugByName = new Map(allSkills.map((s) => [s.name, s.slug]));
  const installStateOf = (name: string): string | undefined => {
    const slug = slugByName.get(name);
    return slug ? skillInstalls[slug] : undefined;
  };

  // The picker offers EVERY workspace skill — a linked one can be re-selected to re-push an
  // updated copy of its files (#74/#105), not only newly-linked skills.
  const linkedNameSet = new Set(linkedSkillNames);

  const toggleNewSkill = (skillId: string) => {
    setSelectedNewIds((prev) =>
      prev.includes(skillId) ? prev.filter((s) => s !== skillId) : [...prev, skillId],
    );
  };

  const openLinkSkills = () => {
    setSelectedNewIds([]);
    setLinkFailed(false);
    setLinked(false);
    setLinkSkillsOpen(true);
  };

  const handleInstallSkills = async () => {
    if (!agent || selectedNewIds.length === 0 || installing) return;
    setInstalling(true);
    setLinkFailed(false);
    try {
      await installAgentSkills(agent.id, selectedNewIds);
      setLinked(true);
      setTimeout(() => {
        setLinkSkillsOpen(false);
        setSelectedNewIds([]);
        setLinked(false);
      }, 900);
    } catch {
      setLinkFailed(true);
    }
    setInstalling(false);
  };

  return (
    <div className="min-h-[100dvh]">
      {/* Back link */}
      <button
        onClick={() => navigate(wsHref(workspaceId, '/agents'))}
        className="inline-flex items-center gap-1.5 mb-5 text-[13px] font-medium text-[#6B5E4E] hover:text-[#C25E3A] transition-colors"
      >
        <ChevronLeft className="w-4 h-4" /> {t('agentDetail.backToAgents')}
      </button>

      {/* Header */}
      <motion.div
        initial={{ opacity: 0, y: 16 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.4 }}
        className="flex items-start gap-4 mb-8"
      >
        <div
          className="w-14 h-14 rounded-full overflow-hidden flex-shrink-0 border-2 flex items-center justify-center"
          style={{ borderColor: statusColor.color }}
        >
          {agent?.avatar ? (
            <img src={agent.avatar} alt={displayName} className="w-full h-full object-cover" />
          ) : (
            <Bot className="w-7 h-7 text-ink-muted" />
          )}
        </div>
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <h1 className="font-['Fraunces',Georgia,serif] text-[32px] font-semibold text-[#2A2318] leading-tight">
              {displayName}
            </h1>
            {agent?.isWorkspaceAgent === true && (
              <span className="inline-flex items-center gap-0.5 px-2 py-0.5 rounded-full text-[11px] font-medium bg-[#D4A843] text-[#2A2318]">
                <Star className="w-3 h-3" /> WA
              </span>
            )}
          </div>
          <div className="mt-1.5 flex items-center gap-2 flex-wrap">
            {agent?.role && (
              <span className="inline-flex items-center px-2 py-0.5 rounded-full text-[11px] font-medium bg-[#E3D7BC] text-[#6B5E4E]">
                {agent.role}
              </span>
            )}
            <span
              className="inline-flex items-center gap-1.5 text-[12px] font-medium"
              style={{ color: statusColor.color }}
            >
              <span className="w-2 h-2 rounded-full" style={{ backgroundColor: statusColor.color }} />
              {t('directory.status.' + status)}
            </span>
          </div>
        </div>
      </motion.div>

      <div className="grid grid-cols-1 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.3fr)] gap-6">
        {/* ── Left: Overview + Health ── */}
        <div className="space-y-6">
          <VellumPanel className="rounded-lg border-[#E3D7BC]">
            <p className="text-[11px] font-semibold uppercase tracking-[0.16em] text-[#A89880] mb-4">
              {t('agentDetail.overview')}
            </p>
            <div className="grid grid-cols-2 gap-4">
              <Field label={t('agentDetail.field.role')}>{agent?.role || '—'}</Field>
              <Field label={t('agentDetail.field.adapter')}>
                <span className="inline-flex items-center gap-1.5">
                  <AdapterIcon className="w-3.5 h-3.5 text-[#6B5E4E]" />
                  <span className="font-mono text-[12px]">{agent?.adapterType || '—'}</span>
                </span>
              </Field>
              <Field label={t('agentDetail.field.inviteStatus')}>
                {agent ? t('directory.status.' + status) : '—'}
              </Field>
              <Field label={t('agentDetail.field.workspaceAgent')}>
                {agent?.isWorkspaceAgent ? t('common.yes') : t('common.no')}
              </Field>
              <div className="col-span-2">
                <Field label={t('agentDetail.field.id')}>
                  <span className="font-mono text-[12px] break-all text-[#6B5E4E]">{id}</span>
                </Field>
              </div>
            </div>
            <div className="mt-4 pt-4 border-t border-[#E3D7BC]">
              <div className="flex items-center justify-between mb-2">
                <p className="text-[11px] font-medium uppercase tracking-[0.12em] text-[#A89880]">
                  {t('agentDetail.field.skills')}
                </p>
                <button
                  onClick={openLinkSkills}
                  className="inline-flex items-center gap-1 px-2 py-0.5 rounded-md text-[11px] font-medium text-[#C25E3A] hover:bg-[#F3D9D0] transition-colors"
                  aria-label={t('agentDetail.linkSkills.add')}
                  title={t('agentDetail.linkSkills.add')}
                >
                  <Plus className="w-3.5 h-3.5" /> {t('agentDetail.linkSkills.add')}
                </button>
              </div>
              {linkedSkillNames.length > 0 ? (
                <div className="flex flex-wrap gap-1.5">
                  {linkedSkillNames.map((s) => {
                    const st = installStateOf(s);
                    return (
                      <span
                        key={s}
                        className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[11px] font-medium bg-[#E3D7BC] text-[#6B5E4E]"
                      >
                        {s}
                        {st === 'installed' && (
                          <CheckCircle2 className="w-3 h-3 text-[#2A6E3A]" aria-label={t('agentDetail.installState.installed')} />
                        )}
                        {st === 'pending' && (
                          <Loader2 className="w-3 h-3 animate-spin text-[#B8860B]" aria-label={t('agentDetail.installState.pending')} />
                        )}
                        {st === 'failed' && (
                          <AlertTriangle className="w-3 h-3 text-[#8A3B22]" aria-label={t('agentDetail.installState.failed')} />
                        )}
                      </span>
                    );
                  })}
                </div>
              ) : (
                <p className="text-[12px] text-[#A89880]">{t('agentDetail.noSkills')}</p>
              )}
            </div>
          </VellumPanel>

          <VellumPanel className="rounded-lg border-[#E3D7BC]">
            <div className="flex items-center justify-between mb-4">
              <p className="text-[11px] font-semibold uppercase tracking-[0.16em] text-[#A89880]">
                {t('agentDetail.health')}
              </p>
              <span
                className="inline-flex items-center gap-1.5 text-[12px] font-medium"
                style={{ color: statusColor.color }}
              >
                <span className="w-2 h-2 rounded-full" style={{ backgroundColor: statusColor.color }} />
                {t('directory.status.' + status)}
              </span>
            </div>
            <div className="space-y-3 text-[13px]">
              <div className="flex items-center justify-between">
                <span className="text-[#6B5E4E]">{t('agentDetail.field.liveness')}</span>
                <span className="text-[#2A2318] font-medium">{t('directory.status.' + status)}</span>
              </div>
              <div className="flex items-center justify-between">
                <span className="text-[#6B5E4E]">{t('agentDetail.field.lastSeen')}</span>
                <span className="text-[#2A2318]" title={formatAbsolute(agent?.lastSeen)}>
                  {agent?.lastSeen ? rel(agent.lastSeen) : t('agentDetail.never')}
                </span>
              </div>
              {/* Why, not just whether (FR-006c). Every way an agent can be unreachable —
                  never placed, its CLI uninstalled, its machine switched off — reaches the
                  business layers as the one word "offline"; this is the only place the
                  difference is allowed to show, because this is the only place it helps.
                  The server sends a code and the sentence is built here, so the same state
                  reads in whichever language the person set (Hiến pháp VI + VII). An
                  unrecognised code still gets a sentence rather than a raw key: a screen
                  that leaks `agentDetail.offlineReason.x` is a screen that told them
                  nothing.

                  The row is labelled for the *place*, not for the verdict, and that is not
                  cosmetic. Liveness is decided on a clock and this is decided on the state
                  of a place, so there is a real window — the workplace shut a moment ago,
                  the three-probe decay has not run yet — where the agent still reads
                  online. Labelling this "why offline" would have printed a contradiction
                  on screen during exactly the window when the person could still act on
                  it. Named for the place, the same sentence is a warning before the fall
                  and the explanation after it. */}
              {agent?.offlineReason && (
                <div className="flex items-start justify-between gap-4 pt-3 border-t border-[#E3D7BC]">
                  <span className="text-[#6B5E4E] shrink-0">
                    {t('agentDetail.offlineReason.label')}
                  </span>
                  <span className="text-[#8A3B22] text-right">
                    {t('agentDetail.offlineReason.' + agent.offlineReason, {
                      defaultValue: t('agentDetail.offlineReason.unknown'),
                    })}
                  </span>
                </div>
              )}
            </div>
          </VellumPanel>
        </div>

        {/* ── Right: Activity (system↔agent run log) ── */}
        <VellumPanel className="rounded-lg border-[#E3D7BC] flex flex-col">
          <div className="flex items-center justify-between mb-4">
            <div className="flex items-center gap-2">
              <Activity className="w-4 h-4 text-[#C25E3A]" />
              <p className="text-[11px] font-semibold uppercase tracking-[0.16em] text-[#A89880]">
                {t('agentDetail.activity')}
              </p>
            </div>
            {runs !== null && (
              <span className="text-[11px] text-[#A89880]">
                {t('agentDetail.runCount', { count: runs.length })}
              </span>
            )}
          </div>

          {error && (
            <div className="mb-3 flex items-center gap-1.5 px-3 py-2 rounded-md bg-[#F3D9D0] text-[12px] text-[#8A3B22] border border-[#E3C0B2]">
              <AlertTriangle className="w-3.5 h-3.5" /> {error}
            </div>
          )}

          {runs === null ? (
            <div className="flex items-center justify-center gap-2 py-16 text-[13px] text-[#A89880]">
              <Loader2 className="w-4 h-4 animate-spin" /> {t('agentDetail.loadingActivity')}
            </div>
          ) : runs.length === 0 ? (
            <div className="flex flex-col items-center justify-center gap-2 py-16 text-center">
              <div className="w-12 h-12 rounded-full bg-[#EDE4CE] flex items-center justify-center">
                <Clock className="w-6 h-6 text-[#A89880]" />
              </div>
              <p className="text-[13px] font-medium text-[#2A2318]">{t('agentDetail.noActivityTitle')}</p>
              <p className="text-[12px] text-[#A89880] max-w-xs">{t('agentDetail.noActivityHint')}</p>
            </div>
          ) : (
            <div className="space-y-2.5">
              {runs.map((run) => (
                <RunRow key={run.id} run={run} />
              ))}
            </div>
          )}

          {runs !== null && runs.length > 0 && (
            <p className="mt-4 flex items-center gap-1.5 text-[11px] text-[#A89880]">
              <CheckCircle2 className="w-3 h-3" /> {t('agentDetail.liveHint')}
            </p>
          )}
        </VellumPanel>
      </div>

      {/* Post-invite skill install (#74) — link more skills + push a one-time install prompt. */}
      <Modal
        isOpen={linkSkillsOpen}
        onClose={() => setLinkSkillsOpen(false)}
        title={t('agentDetail.linkSkills.title', { name: displayName })}
        footer={
          <>
            <button
              onClick={() => setLinkSkillsOpen(false)}
              className="px-4 py-2 rounded-md text-[13px] font-medium bg-[#EDE4CE] text-[#2A2318] border border-[#E3D7BC] hover:bg-[#E3D7BC] transition-colors"
            >
              {t('common.cancel')}
            </button>
            <button
              onClick={handleInstallSkills}
              disabled={selectedNewIds.length === 0 || installing}
              className={cn(
                'inline-flex items-center gap-2 px-4 py-2 rounded-md text-[13px] font-medium transition-all',
                selectedNewIds.length > 0 && !installing
                  ? 'bg-[#C25E3A] text-white hover:bg-[#D97B5A]'
                  : 'bg-[#E3D7BC] text-[#A89880] cursor-not-allowed',
              )}
            >
              {installing && <Loader2 className="w-3.5 h-3.5 animate-spin" />}
              {linkFailed
                ? t('agentDetail.linkSkills.retry')
                : installing
                  ? t('agentDetail.linkSkills.sending')
                  : t('agentDetail.linkSkills.confirm')}
            </button>
          </>
        }
      >
        <p className="text-[12px] text-[#6B5E4E] mb-3">{t('agentDetail.linkSkills.hint')}</p>
        {allSkills.length === 0 ? (
          <p className="text-[12px] text-[#A89880]">{t('agentDetail.linkSkills.noneAvailable')}</p>
        ) : (
          <div className="flex flex-wrap gap-1.5">
            {allSkills.map((skill) => {
              const linked = linkedNameSet.has(skill.name);
              const selected = selectedNewIds.includes(skill.id);
              return (
                <button
                  key={skill.id}
                  onClick={() => toggleNewSkill(skill.id)}
                  title={linked ? t('agentDetail.linkSkills.reinstallHint') : undefined}
                  className={cn(
                    'inline-flex items-center gap-1 px-3 py-1.5 rounded-full text-[11px] font-medium transition-all',
                    selected
                      ? 'bg-[#C25E3A] text-white'
                      : 'bg-[#E3D7BC] text-[#6B5E4E] hover:bg-[#D9CDB8]',
                  )}
                >
                  {selected && <Check className="w-3 h-3" />}
                  {skill.name}
                  {linked && !selected && (
                    <span className="text-[9px] uppercase tracking-wide text-[#A89880]">
                      {t('agentDetail.linkSkills.linkedTag')}
                    </span>
                  )}
                </button>
              );
            })}
          </div>
        )}
        {linked && (
          <p className="mt-4 flex items-center gap-1.5 px-3 py-2 rounded-md bg-[#D8EADD] text-[12px] text-[#2A6E3A]">
            <CheckCircle2 className="w-3.5 h-3.5" /> {t('agentDetail.linkSkills.sent')}
          </p>
        )}
        {linkFailed && (
          <p className="mt-4 flex items-center gap-1.5 px-3 py-2 rounded-md bg-[#F3D9D0] text-[12px] text-[#8A3B22] border border-[#E3C0B2]">
            <AlertTriangle className="w-3.5 h-3.5" /> {t('agentDetail.linkSkills.sendFailed')}
          </p>
        )}
      </Modal>
    </div>
  );
}
