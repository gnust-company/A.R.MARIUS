// The plan gate, from the patron's side (spec 001 FR-011 → FR-014).
//
// This page exists so the patron can do exactly one thing well: read what the Leader
// proposes and answer it. Three buttons, no fourth path, and no default — the system
// never decides here, which is the whole point of the gate.
import { useCallback, useEffect, useState } from 'react';
import { useParams, useNavigate } from 'react-router';
import { useTranslation } from 'react-i18next';
import { ChevronLeft, Check, PenLine, MessageCircleQuestion } from 'lucide-react';

import PageTitle from '@/components/PageTitle';
import StatusChip from '@/components/StatusChip';
import VellumPanel from '@/components/VellumPanel';
import {
  approveProjectContext,
  decideProjectPlan,
  getProjectContext,
  getProjectPlan,
  type PlanDTO,
  type PlanDecisionValue,
  type ProjectContextDTO,
  type ProjectContextViewDTO,
} from '@/lib/api';
import { subscribeProjectEvents } from '@/lib/sse';
import { cn, wsHref } from '@/lib/utils';

/** A context part. Empty reads as "không có" — absent must never look like a gap. */
function ContextPart({ label, value }: { label: string; value: string }) {
  const { t } = useTranslation();
  return (
    <div className="mb-4 last:mb-0">
      <div className="font-body font-medium text-body-xs uppercase tracking-wide text-ink-muted">
        {label}
      </div>
      <p className="font-body text-body-sm text-ink whitespace-pre-wrap mt-1">
        {value.trim() || <span className="text-ink-muted italic">{t('projectPlan.empty')}</span>}
      </p>
    </div>
  );
}

function ContextCard({ context, heading }: { context: ProjectContextDTO; heading: string }) {
  const { t } = useTranslation();
  return (
    <VellumPanel className="p-5 mb-4">
      <div className="flex items-center justify-between mb-3">
        <h3 className="font-display text-h4 text-ink">{heading}</h3>
        <span className="font-body text-body-xs text-ink-muted">
          {t('projectPlan.contextVersion', { version: context.version })}
        </span>
      </div>
      <ContextPart label={t('projectPlan.objective')} value={context.objective} />
      <ContextPart label={t('projectPlan.background')} value={context.background} />
      <ContextPart label={t('projectPlan.constraints')} value={context.constraints} />
      <ContextPart label={t('projectPlan.scope')} value={context.scope} />
      <ContextPart label={t('projectPlan.principles')} value={context.principles} />
    </VellumPanel>
  );
}

export default function ProjectPlan() {
  const { workspaceId, id: projectId } = useParams();
  const navigate = useNavigate();
  const { t } = useTranslation();

  const [context, setContext] = useState<ProjectContextViewDTO | null>(null);
  const [plan, setPlan] = useState<PlanDTO | null>(null);
  const [note, setNote] = useState('');
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    if (!projectId) return;
    try {
      setContext(await getProjectContext(projectId));
    } catch {
      setContext(null);
    }
    try {
      setPlan(await getProjectPlan(projectId));
    } catch {
      // 404 until the Leader submits its first plan — an empty state, not an error.
      setPlan(null);
    }
  }, [projectId]);

  useEffect(() => {
    // Deferred by a microtask so the first paint is never blocked by a synchronous
    // setState inside the effect body (cascading renders).
    let cancelled = false;
    void Promise.resolve().then(() => {
      if (!cancelled) void load();
    });
    return () => {
      cancelled = true;
    };
  }, [load]);

  // Push, not poll (Constitution IV): the Leader may submit while this page is open.
  useEffect(() => {
    if (!projectId) return;
    return subscribeProjectEvents(projectId, (event) => {
      if (event.type.startsWith('plan.') || event.type.startsWith('context.')) {
        void load();
      }
    });
  }, [projectId, load]);

  const decide = async (decision: PlanDecisionValue) => {
    if (!projectId) return;
    if (decision !== 'duyet' && !note.trim()) {
      setError(t('projectPlan.noteRequired'));
      return;
    }
    setBusy(true);
    setError(null);
    // Everything conditional is worked out before the block. The React Compiler has no
    // lowering for a conditional *expression* inside try/catch and drops the whole
    // component when it meets one; none of these depend on the call anyway.
    const decided =
      decision === 'duyet'
        ? t('projectPlan.decidedApproved')
        : decision === 'yeu_cau_chinh'
          ? t('projectPlan.decidedChanges')
          : t('projectPlan.decidedAsked');
    const noteOrNone = note.trim() || undefined;
    const failed = t('projectPlan.loadFailed');
    try {
      const updated = await decideProjectPlan(projectId, decision, noteOrNone);
      setPlan(updated);
      setNote('');
      setMessage(decided);
    } catch (e) {
      setError(e instanceof Error ? e.message : failed);
    }
    setBusy(false);
  };

  const approveContext = async () => {
    if (!projectId) return;
    setBusy(true);
    const failed = t('projectPlan.loadFailed');
    try {
      await approveProjectContext(projectId, true);
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : failed);
    }
    setBusy(false);
  };

  const awaitingDecision = plan?.status === 'submitted';

  return (
    <div className="max-w-3xl mx-auto pb-16">
      <button
        type="button"
        onClick={() => navigate(wsHref(workspaceId, `/projects/${projectId}`))}
        className="inline-flex items-center gap-1 font-body text-body-sm text-ink-muted hover:text-ink mb-4"
      >
        <ChevronLeft className="w-4 h-4" />
        {t('projectPlan.back')}
      </button>

      <PageTitle title={t('projectPlan.title')} subtitle={t('projectPlan.subtitle')} />

      {/* ── Context ─────────────────────────────────────────────────────── */}
      <h2 className="font-display text-h3 text-ink mt-6 mb-3">
        {t('projectPlan.contextHeading')}
      </h2>
      {context?.pending && (
        <>
          <ContextCard context={context.pending} heading={t('projectPlan.contextPending')} />
          <button
            type="button"
            disabled={busy}
            onClick={approveContext}
            className="inline-flex items-center gap-2 rounded-md bg-[#2A6E3A] px-4 py-2 font-body font-medium text-body-sm text-white disabled:opacity-50 mb-6"
          >
            <Check className="w-4 h-4" />
            {t('projectPlan.approveContext')}
          </button>
        </>
      )}
      {context?.approved && (
        <ContextCard context={context.approved} heading={t('projectPlan.contextApproved')} />
      )}
      {!context?.approved && !context?.pending && (
        <p className="font-body text-body-sm text-ink-muted mb-6">
          {t('projectPlan.contextEmpty')}
        </p>
      )}

      {/* ── Plan ────────────────────────────────────────────────────────── */}
      <h2 className="font-display text-h3 text-ink mt-8 mb-3">{t('projectPlan.planHeading')}</h2>
      {!plan && (
        <p className="font-body text-body-sm text-ink-muted">{t('projectPlan.planEmpty')}</p>
      )}

      {plan && (
        <VellumPanel className="p-5">
          <div className="flex items-center justify-between mb-4">
            <span className="font-body text-body-xs text-ink-muted">
              {t('projectPlan.planVersion', { version: plan.version })}
            </span>
            <StatusChip
              status={plan.status === 'approved' ? 'done' : 'in_review'}
              label={t(`projectPlan.statusLabel.${plan.status}`)}
            />
          </div>

          <ContextPart label={t('projectPlan.summary')} value={plan.summary} />
          <ContextPart label={t('projectPlan.risks')} value={plan.risks} />
          <ContextPart label={t('projectPlan.milestones')} value={plan.milestones} />

          <div className="mt-5">
            <div className="font-body font-medium text-body-xs uppercase tracking-wide text-ink-muted mb-2">
              {t('projectPlan.items')}
            </div>
            {plan.items.length === 0 ? (
              <p className="font-body text-body-sm text-ink-muted italic">
                {t('projectPlan.itemsEmpty')}
              </p>
            ) : (
              <ol className="space-y-3">
                {plan.items.map((item, index) => (
                  <li key={item.id} className="border-l-2 border-vellum-dark pl-3">
                    <div className="font-body font-medium text-body-sm text-ink">
                      {index + 1}. {item.title}
                    </div>
                    {item.description && (
                      <p className="font-body text-body-sm text-ink-muted whitespace-pre-wrap">
                        {item.description}
                      </p>
                    )}
                    {item.definition_of_done && (
                      <p className="font-body text-body-xs text-ink-muted mt-1">
                        <span className="uppercase tracking-wide">
                          {t('projectPlan.itemDefinitionOfDone')}:
                        </span>{' '}
                        {item.definition_of_done}
                      </p>
                    )}
                  </li>
                ))}
              </ol>
            )}
          </div>

          {plan.patron_note && (
            <div className="mt-5 rounded-md bg-vellum-dark/40 p-3">
              <div className="font-body font-medium text-body-xs uppercase tracking-wide text-ink-muted">
                {t('projectPlan.patronNote')}
              </div>
              <p className="font-body text-body-sm text-ink whitespace-pre-wrap mt-1">
                {plan.patron_note}
              </p>
            </div>
          )}
        </VellumPanel>
      )}

      {/* ── The three choices ───────────────────────────────────────────── */}
      {awaitingDecision && (
        <VellumPanel className="p-5 mt-6">
          <h3 className="font-display text-h4 text-ink">{t('projectPlan.decisionHeading')}</h3>
          <p className="font-body text-body-sm text-ink-muted mt-1 mb-3">
            {t('projectPlan.decisionHint')}
          </p>

          <textarea
            value={note}
            onChange={(e) => setNote(e.target.value)}
            placeholder={t('projectPlan.notePlaceholder')}
            rows={3}
            className="w-full rounded-md border border-vellum-dark bg-vellum px-3 py-2 font-body text-body-sm text-ink"
          />

          <div className="flex flex-wrap gap-2 mt-3">
            <button
              type="button"
              disabled={busy}
              onClick={() => decide('duyet')}
              className="inline-flex items-center gap-2 rounded-md bg-[#2A6E3A] px-4 py-2 font-body font-medium text-body-sm text-white disabled:opacity-50"
            >
              <Check className="w-4 h-4" />
              {busy ? t('projectPlan.deciding') : t('projectPlan.approve')}
            </button>
            <button
              type="button"
              disabled={busy}
              onClick={() => decide('yeu_cau_chinh')}
              className="inline-flex items-center gap-2 rounded-md border border-vellum-dark px-4 py-2 font-body font-medium text-body-sm text-ink disabled:opacity-50"
            >
              <PenLine className="w-4 h-4" />
              {t('projectPlan.requestChanges')}
            </button>
            <button
              type="button"
              disabled={busy}
              onClick={() => decide('hoi_lai')}
              className="inline-flex items-center gap-2 rounded-md border border-vellum-dark px-4 py-2 font-body font-medium text-body-sm text-ink disabled:opacity-50"
            >
              <MessageCircleQuestion className="w-4 h-4" />
              {t('projectPlan.askBack')}
            </button>
          </div>
        </VellumPanel>
      )}

      {(message || error) && (
        <p
          className={cn(
            'font-body text-body-sm mt-4',
            error ? 'text-[#B84A32]' : 'text-[#2A6E3A]',
          )}
        >
          {error ?? message}
        </p>
      )}
    </div>
  );
}
