// @ts-nocheck
// Single-agent detail view (#72). Opened by clicking an agent card in the Directory. The
// right column is the system↔agent interaction log the owner tracks: every Run the system
// dispatched to this agent (assignment, mention, commission, …), each expandable to its
// durable per-run trace (RunEvent). Data is read-only and polls so a live run updates in place.
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
  CheckCircle2,
} from 'lucide-react';
import { useMockStore } from '@/store/mockStore';
import type { AgentStatus } from '@/store/mockStore';
import { listMariusRuns, listRunEvents, type RunDTO, type RunEventDTO } from '@/lib/api';
import VellumPanel from '@/components/VellumPanel';
import { cn, wsHref } from '@/lib/utils';

// ─── Status palette (mirrors Directory's Scriptorium tones) ───────────────────

const STATUS_COLORS: Record<AgentStatus, { color: string; label: string }> = {
  online: { color: '#4A9E6B', label: 'online' },
  working: { color: '#D4A843', label: 'working' },
  idle: { color: '#A89880', label: 'idle' },
  offline: { color: '#8B7A6A', label: 'offline' },
  hung: { color: '#C25E3A', label: 'hung' },
  checking: { color: '#D97B5A', label: 'checking' },
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
  hermes_gateway: Globe,
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
          {run.trigger_detail && (
            <p className="mt-1 text-[12px] text-[#6B5E4E] break-words line-clamp-2">{run.trigger_detail}</p>
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
  const mariuses = useMockStore((s) => s.mariuses);
  const agent = mariuses.find((m) => m.id === id);

  const [runs, setRuns] = useState<RunDTO[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  // Poll the agent's run log so a live run advances in place (the openclaw detail view
  // refetches on an interval too). Read-only — no mutations from this screen.
  useEffect(() => {
    if (!workspaceId || !id) return;
    let alive = true;
    const load = () => {
      listMariusRuns(workspaceId, id)
        .then((rows) => { if (alive) { setRuns(rows); setError(null); } })
        .catch((e) => { if (alive) setError(e?.message || 'Failed to load runs'); });
    };
    load();
    const timer = setInterval(load, 15000);
    return () => { alive = false; clearInterval(timer); };
  }, [workspaceId, id]);

  const status: AgentStatus = agent?.status || 'offline';
  const statusColor = STATUS_COLORS[status] || STATUS_COLORS.offline;
  const displayName = agent?.displayName || agent?.name || t('agentDetail.agentFallback');
  const AdapterIcon = ADAPTER_ICON[agent?.adapterType || ''] || Globe;
  const skills = agent?.skills || [];

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
              {agent?.gatewayUrl && (
                <div className="col-span-2">
                  <Field label={t('agentDetail.field.gateway')}>
                    <span className="font-mono text-[12px] break-all">{agent.gatewayUrl}</span>
                  </Field>
                </div>
              )}
              <div className="col-span-2">
                <Field label={t('agentDetail.field.id')}>
                  <span className="font-mono text-[12px] break-all text-[#6B5E4E]">{id}</span>
                </Field>
              </div>
            </div>
            {skills.length > 0 && (
              <div className="mt-4 pt-4 border-t border-[#E3D7BC]">
                <p className="text-[11px] font-medium uppercase tracking-[0.12em] text-[#A89880] mb-2">
                  {t('agentDetail.field.skills')}
                </p>
                <div className="flex flex-wrap gap-1.5">
                  {skills.map((s) => (
                    <span key={s} className="px-2 py-0.5 rounded-full text-[11px] font-medium bg-[#E3D7BC] text-[#6B5E4E]">
                      {s}
                    </span>
                  ))}
                </div>
              </div>
            )}
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
    </div>
  );
}
