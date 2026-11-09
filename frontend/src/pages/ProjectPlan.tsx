// The plan gate, from the patron's side (spec 001 FR-011 → FR-014).
//
// This page exists so the patron can do exactly one thing well: read what the Leader
// proposes and answer it. Three buttons, no fourth path, and no default — the system
// never decides here, which is the whole point of the gate.
import { useCallback, useEffect, useState, type ReactNode } from 'react';
import { useParams } from 'react-router';
import { useTranslation } from 'react-i18next';
import { Check, PenLine, MessageCircleQuestion, AlertTriangle, CheckCircle2 } from 'lucide-react';

import StatusChip from '@/components/StatusChip';
import ProjectHeader from '@/components/project/ProjectHeader';
import { useAppStore } from '@/store/appStore';
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
import { cn } from '@/lib/utils';
import { errorText } from '@/lib/errors';

const PART_LABEL = 'font-body text-[11px] text-ink-muted';
const SECTION_TITLE = 'font-display text-[20px] font-normal tracking-[-0.01em] text-ink-strong';

/** A context part. Empty reads as "không có" — absent must never look like a gap. */
function ContextPart({ label, value }: { label: string; value: string }) {
  const { t } = useTranslation();
  return (
    <div className="py-3 border-t border-line first:border-t-0 first:pt-0">
      <div className={PART_LABEL}>{label}</div>
      <p className="mt-1 font-body text-[14px] leading-relaxed text-ink whitespace-pre-wrap break-words">
        {value.trim() || <span className="text-ink-muted">{t('projectPlan.empty')}</span>}
      </p>
    </div>
  );
}

/** A section of the plan document: a Lora heading over the Leader's own text. */
function PlanSection({ label, value }: { label: string; value: string }) {
  const { t } = useTranslation();
  return (
    <div className="mt-6 first:mt-0">
      <h3 className={SECTION_TITLE}>{label}</h3>
      <p className="mt-2 font-body text-[14px] leading-[1.75] text-ink-light whitespace-pre-wrap break-words">
        {value.trim() || <span className="text-ink-muted">{t('projectPlan.empty')}</span>}
      </p>
    </div>
  );
}

/** One version of the context. Its state — waiting on the patron (gold) or in force (success) —
 *  is drawn as the status chip rather than a second title. */
function ContextCard({
  context,
  heading,
  pending,
  children,
}: {
  context: ProjectContextDTO;
  heading: string;
  pending: boolean;
  children?: ReactNode;
}) {
  const { t } = useTranslation();
  return (
    <section className={cn('surface p-6', pending && 'border-gold/40')}>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <span className="eyebrow">{t('projectView.contextEyebrow', { version: context.version })}</span>
        <StatusChip status={pending ? 'planning' : 'done'} label={heading} />
      </div>
      <h2 className="mt-2 mb-4 font-display text-[24px] font-normal leading-tight tracking-[-0.02em] text-ink-strong">
        {t('projectPlan.contextHeading')}
      </h2>
      <ContextPart label={t('projectPlan.objective')} value={context.objective} />
      <ContextPart label={t('projectPlan.background')} value={context.background} />
      <ContextPart label={t('projectPlan.constraints')} value={context.constraints} />
      <ContextPart label={t('projectPlan.scope')} value={context.scope} />
      <ContextPart label={t('projectPlan.principles')} value={context.principles} />
      {children}
    </section>
  );
}

export default function ProjectPlan() {
  const { id: projectId } = useParams();
  const { t } = useTranslation();
  const project = useAppStore((s) => s.projects.find((p) => p.id === projectId));

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
    try {
      const updated = await decideProjectPlan(projectId, decision, noteOrNone);
      setPlan(updated);
      setNote('');
      setMessage(decided);
    } catch (e) {
      setError(errorText(e, t));
    }
    setBusy(false);
  };

  const approveContext = async () => {
    if (!projectId) return;
    setBusy(true);
    try {
      await approveProjectContext(projectId, true);
      await load();
    } catch (e) {
      setError(errorText(e, t));
    }
    setBusy(false);
  };

  const awaitingDecision = plan?.status === 'submitted';

  const message_ = (message || error) && (
    <p
      role={error ? 'alert' : 'status'}
      className={cn(
        'flex items-start gap-2 rounded-md border px-4 py-3 font-body text-[14px]',
        error ? 'bg-danger-soft border-danger/30 text-danger' : 'bg-success-soft border-success/30 text-success',
      )}
    >
      {error ? (
        <AlertTriangle className="w-[18px] h-[18px] mt-0.5 shrink-0" />
      ) : (
        <CheckCircle2 className="w-[18px] h-[18px] mt-0.5 shrink-0" />
      )}
      {error ?? message}
    </p>
  );

  return (
    <div className="mx-auto w-full max-w-[1240px] flex flex-col pb-16">
      {project && <ProjectHeader project={project} active="plan" />}

      <div className="grid gap-[18px] lg:grid-cols-[minmax(0,1.5fr)_minmax(0,.8fr)] items-start">
        {/* ── The plan, and the patron's three choices ───────────────────── */}
        <div className="flex min-w-0 flex-col gap-[18px]">
          {!plan && (
            <section className="surface p-6 sm:p-7">
              <span className="eyebrow">{t('projectPlan.planHeading')}</span>
              <p className="mt-3 font-body text-[14px] leading-relaxed text-ink-muted">{t('projectPlan.planEmpty')}</p>
            </section>
          )}

          {plan && (
            <section className="surface p-6 sm:p-7">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <span className="eyebrow">{t('projectView.planEyebrow', { version: plan.version })}</span>
                <StatusChip
                  status={plan.status === 'approved' ? 'done' : plan.status === 'submitted' ? 'planning' : 'in_review'}
                  label={t(`projectPlan.statusLabel.${plan.status}`)}
                />
              </div>
              <h2 className="mt-2 mb-5 font-display text-[28px] font-normal leading-tight tracking-[-0.02em] text-ink-strong">
                {t('projectPlan.planHeading')}
              </h2>

              <PlanSection label={t('projectPlan.summary')} value={plan.summary} />
              <PlanSection label={t('projectPlan.risks')} value={plan.risks} />
              <PlanSection label={t('projectPlan.milestones')} value={plan.milestones} />

              <div className="mt-7">
                <h3 className={SECTION_TITLE}>{t('projectPlan.items')}</h3>
                {plan.items.length === 0 ? (
                  <p className="mt-2 font-body text-[14px] text-ink-muted">{t('projectPlan.itemsEmpty')}</p>
                ) : (
                  <ol className="mt-3 flex flex-col">
                    {plan.items.map((item, index) => (
                      <li key={item.id} className="flex gap-3.5 py-4 border-t border-line">
                        <span className="grid place-items-center w-8 h-8 shrink-0 rounded-full border border-line-strong font-mono text-[11px] text-sapphire-strong">
                          {index + 1}
                        </span>
                        <div className="min-w-0 flex-1 flex flex-col gap-1">
                          <div className="font-display text-[17px] leading-snug text-ink-strong break-words">{item.title}</div>
                          {item.description && (
                            <p className="font-body text-[14px] leading-relaxed text-ink-light whitespace-pre-wrap break-words">
                              {item.description}
                            </p>
                          )}
                          {item.definition_of_done && (
                            <p className="font-body text-[13px] text-ink-light break-words">
                              <span className="font-semibold text-ink">{t('projectPlan.itemDefinitionOfDone')}:</span>{' '}
                              {item.definition_of_done}
                            </p>
                          )}
                        </div>
                      </li>
                    ))}
                  </ol>
                )}
              </div>

              {plan.patron_note && (
                <div className="mt-5 rounded-md border border-line bg-canvas-deep p-4">
                  <div className={PART_LABEL}>{t('projectPlan.patronNote')}</div>
                  <p className="mt-1 font-body text-[14px] leading-relaxed text-ink whitespace-pre-wrap break-words">
                    {plan.patron_note}
                  </p>
                </div>
              )}
            </section>
          )}

          {/* ── The three choices ── */}
          {awaitingDecision && (
            <section className="surface border-gold/40 p-6 flex flex-col gap-3.5">
              <div>
                <span className="eyebrow">{t('projectView.decisionEyebrow')}</span>
                <h3 className="mt-1.5 font-display text-[22px] font-normal text-ink-strong">{t('projectPlan.decisionHeading')}</h3>
                <p className="mt-1 font-body text-[14px] leading-relaxed text-ink-light">{t('projectPlan.decisionHint')}</p>
              </div>

              <textarea
                value={note}
                onChange={(e) => setNote(e.target.value)}
                placeholder={t('projectPlan.notePlaceholder')}
                aria-label={t('projectPlan.patronNote')}
                rows={3}
                className="field py-3 leading-relaxed resize-y"
              />

              <div className="flex flex-wrap gap-2.5">
                <button type="button" disabled={busy} onClick={() => decide('duyet')} className="btn btn-primary">
                  <Check className="w-4 h-4" />
                  {busy ? t('projectPlan.deciding') : t('projectPlan.approve')}
                </button>
                <button type="button" disabled={busy} onClick={() => decide('yeu_cau_chinh')} className="btn btn-secondary">
                  <PenLine className="w-4 h-4" />
                  {t('projectPlan.requestChanges')}
                </button>
                <button type="button" disabled={busy} onClick={() => decide('hoi_lai')} className="btn btn-secondary">
                  <MessageCircleQuestion className="w-4 h-4" />
                  {t('projectPlan.askBack')}
                </button>
              </div>
            </section>
          )}

          {message_}
        </div>

        {/* ── Context ─────────────────────────────────────────────────────── */}
        <aside className="flex min-w-0 flex-col gap-[18px]">
          {context?.pending && (
            <ContextCard context={context.pending} heading={t('projectPlan.contextPending')} pending>
              <button
                type="button"
                disabled={busy}
                onClick={approveContext}
                // One primary per view: when the plan is also waiting, its decision is the main act.
                className={cn('btn mt-4 self-start', awaitingDecision ? 'btn-secondary' : 'btn-primary')}
              >
                <Check className="w-4 h-4" />
                {t('projectPlan.approveContext')}
              </button>
            </ContextCard>
          )}
          {context?.approved && (
            <ContextCard context={context.approved} heading={t('projectPlan.contextApproved')} pending={false} />
          )}
          {!context?.approved && !context?.pending && (
            <section className="surface p-6">
              <span className="eyebrow">{t('projectPlan.contextHeading')}</span>
              <p className="mt-3 font-body text-[14px] leading-relaxed text-ink-muted">{t('projectPlan.contextEmpty')}</p>
            </section>
          )}
        </aside>
      </div>
    </div>
  );
}
