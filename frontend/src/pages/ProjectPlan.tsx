// The plan gate, from the patron's side (spec 001 FR-011 → FR-014).
//
// This page exists so the patron can do exactly one thing well: read what the Leader
// proposes and answer it. Three buttons, no fourth path, and no default — the system
// never decides here, which is the whole point of the gate.
import { useCallback, useEffect, useState } from 'react';
import { useParams, Link } from 'react-router';
import { useTranslation } from 'react-i18next';
import { ChevronLeft, Check, PenLine, MessageCircleQuestion, AlertTriangle, CheckCircle2 } from 'lucide-react';

import PageTitle from '@/components/PageTitle';
import StatusChip from '@/components/StatusChip';
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
import { errorText } from '@/lib/errors';

const SECTION_TITLE = 'font-display text-[22px] font-medium text-ink';
const PART_LABEL = 'font-body text-body-sm font-medium text-ink-light';
const SECONDARY_BUTTON =
  'inline-flex items-center gap-2 min-h-[44px] px-4 rounded-md bg-paper border border-line-strong font-body text-body-md font-medium text-ink hover:bg-inset transition-colors disabled:cursor-not-allowed disabled:text-ink-muted';
const PRIMARY_BUTTON =
  'inline-flex items-center gap-2 min-h-[44px] px-[18px] rounded-md bg-ink font-body text-body-md font-medium text-paper hover:bg-ink/85 transition-colors disabled:cursor-not-allowed disabled:bg-line disabled:text-ink-muted';

/** A context part. Empty reads as "không có" — absent must never look like a gap. */
function ContextPart({ label, value }: { label: string; value: string }) {
  const { t } = useTranslation();
  return (
    <div>
      <div className={PART_LABEL}>{label}</div>
      <p className="font-body text-body-md text-ink whitespace-pre-wrap break-words mt-1">
        {value.trim() || <span className="text-ink-muted">{t('projectPlan.empty')}</span>}
      </p>
    </div>
  );
}

/** One version of the context. The heading is its state — waiting on the patron (gold) or in
 *  force (verdigris) — so it is drawn as the status chip rather than a second title. */
function ContextCard({
  context,
  heading,
  pending,
}: {
  context: ProjectContextDTO;
  heading: string;
  pending: boolean;
}) {
  const { t } = useTranslation();
  return (
    <div className="bg-paper border border-line rounded-xl p-5 flex flex-col gap-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <StatusChip status={pending ? 'in_review' : 'done'} size="md" label={heading} />
        <span className="font-mono text-mono-sm text-ink-muted">
          {t('projectPlan.contextVersion', { version: context.version })}
        </span>
      </div>
      <ContextPart label={t('projectPlan.objective')} value={context.objective} />
      <ContextPart label={t('projectPlan.background')} value={context.background} />
      <ContextPart label={t('projectPlan.constraints')} value={context.constraints} />
      <ContextPart label={t('projectPlan.scope')} value={context.scope} />
      <ContextPart label={t('projectPlan.principles')} value={context.principles} />
    </div>
  );
}

export default function ProjectPlan() {
  const { workspaceId, id: projectId } = useParams();
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


  return (
    <div className="mx-auto w-full max-w-3xl flex flex-col gap-6 pb-16">
      <div className="flex flex-col gap-3">
        <Link
          to={wsHref(workspaceId, `/projects/${projectId}`)}
          className="inline-flex items-center gap-1 self-start min-h-[44px] -ml-2 px-2 rounded-md font-body text-body-md text-ink-light hover:text-ink hover:bg-inset transition-colors"
        >
          <ChevronLeft className="w-4 h-4" />
          {t('projectPlan.back')}
        </Link>
        <PageTitle title={t('projectPlan.title')} subtitle={t('projectPlan.subtitle')} />
      </div>

      {/* ── Context ─────────────────────────────────────────────────────── */}
      <section className="flex flex-col gap-3">
        <h2 className={SECTION_TITLE}>{t('projectPlan.contextHeading')}</h2>
        {context?.pending && (
          <>
            <ContextCard context={context.pending} heading={t('projectPlan.contextPending')} pending />
            <button
              type="button"
              disabled={busy}
              onClick={approveContext}
              // One primary per view: when the plan is also waiting, its decision is the main act.
              className={cn(awaitingDecision ? SECONDARY_BUTTON : PRIMARY_BUTTON, 'self-start')}
            >
              <Check className="w-4 h-4" />
              {t('projectPlan.approveContext')}
            </button>
          </>
        )}
        {context?.approved && (
          <ContextCard context={context.approved} heading={t('projectPlan.contextApproved')} pending={false} />
        )}
        {!context?.approved && !context?.pending && (
          <p className="bg-paper border border-line rounded-xl px-5 py-5 font-body text-body-md text-ink-muted">
            {t('projectPlan.contextEmpty')}
          </p>
        )}
      </section>

      {/* ── Plan ────────────────────────────────────────────────────────── */}
      <section className="flex flex-col gap-3">
        <h2 className={SECTION_TITLE}>{t('projectPlan.planHeading')}</h2>
        {!plan && (
          <p className="bg-paper border border-line rounded-xl px-5 py-5 font-body text-body-md text-ink-muted">
            {t('projectPlan.planEmpty')}
          </p>
        )}

        {plan && (
          <div className="bg-paper border border-line rounded-xl p-5 flex flex-col gap-4">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <StatusChip
                status={plan.status === 'approved' ? 'done' : 'in_review'}
                size="md"
                label={t(`projectPlan.statusLabel.${plan.status}`)}
              />
              <span className="font-mono text-mono-sm text-ink-muted">
                {t('projectPlan.planVersion', { version: plan.version })}
              </span>
            </div>

            <ContextPart label={t('projectPlan.summary')} value={plan.summary} />
            <ContextPart label={t('projectPlan.risks')} value={plan.risks} />
            <ContextPart label={t('projectPlan.milestones')} value={plan.milestones} />

            <div className="flex flex-col gap-2">
              <div className={PART_LABEL}>{t('projectPlan.items')}</div>
              {plan.items.length === 0 ? (
                <p className="font-body text-body-md text-ink-muted">{t('projectPlan.itemsEmpty')}</p>
              ) : (
                <ol className="flex flex-col gap-2">
                  {plan.items.map((item, index) => (
                    <li key={item.id} className="flex gap-3 bg-inset border border-line rounded-lg p-3.5">
                      <span className="w-7 h-7 shrink-0 rounded-full bg-paper border border-line-strong flex items-center justify-center font-body text-body-sm font-semibold text-ink-light">
                        {index + 1}
                      </span>
                      <div className="min-w-0 flex-1 flex flex-col gap-1">
                        <div className="font-body font-medium text-[15px] text-ink break-words">{item.title}</div>
                        {item.description && (
                          <p className="font-body text-body-md text-ink-light whitespace-pre-wrap break-words">
                            {item.description}
                          </p>
                        )}
                        {item.definition_of_done && (
                          <p className="font-body text-body-sm text-ink-light break-words">
                            <span className="font-medium text-ink">{t('projectPlan.itemDefinitionOfDone')}:</span>{' '}
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
              <div className="rounded-lg bg-inset border border-line p-3.5">
                <div className={PART_LABEL}>{t('projectPlan.patronNote')}</div>
                <p className="font-body text-body-md text-ink whitespace-pre-wrap break-words mt-1">
                  {plan.patron_note}
                </p>
              </div>
            )}
          </div>
        )}
      </section>

      {/* ── The three choices ───────────────────────────────────────────── */}
      {awaitingDecision && (
        <section className="bg-paper border border-line-strong rounded-xl p-5 flex flex-col gap-3">
          <div>
            <h3 className="font-display text-[20px] font-medium text-ink">{t('projectPlan.decisionHeading')}</h3>
            <p className="font-body text-body-md text-ink-light mt-1">{t('projectPlan.decisionHint')}</p>
          </div>

          <textarea
            value={note}
            onChange={(e) => setNote(e.target.value)}
            placeholder={t('projectPlan.notePlaceholder')}
            aria-label={t('projectPlan.patronNote')}
            rows={3}
            className="w-full rounded-md border border-line bg-inset px-3.5 py-2.5 font-body text-body-md text-ink placeholder:text-ink-muted focus:outline-none focus:border-terracotta focus:ring-[3px] focus:ring-terracotta/15 transition-colors resize-y"
          />

          <div className="flex flex-wrap gap-2">
            <button type="button" disabled={busy} onClick={() => decide('duyet')} className={PRIMARY_BUTTON}>
              <Check className="w-4 h-4" />
              {busy ? t('projectPlan.deciding') : t('projectPlan.approve')}
            </button>
            <button type="button" disabled={busy} onClick={() => decide('yeu_cau_chinh')} className={SECONDARY_BUTTON}>
              <PenLine className="w-4 h-4" />
              {t('projectPlan.requestChanges')}
            </button>
            <button type="button" disabled={busy} onClick={() => decide('hoi_lai')} className={SECONDARY_BUTTON}>
              <MessageCircleQuestion className="w-4 h-4" />
              {t('projectPlan.askBack')}
            </button>
          </div>
        </section>
      )}

      {(message || error) && (
        <p
          role={error ? 'alert' : 'status'}
          className={cn(
            'flex items-start gap-2 rounded-lg border px-4 py-3 font-body text-body-md',
            error
              ? 'bg-vermilion-bg border-vermilion/30 text-vermilion-ink'
              : 'bg-verdigris-bg border-verdigris/30 text-verdigris-ink',
          )}
        >
          {error ? (
            <AlertTriangle className="w-[18px] h-[18px] mt-0.5 shrink-0" />
          ) : (
            <CheckCircle2 className="w-[18px] h-[18px] mt-0.5 shrink-0" />
          )}
          {error ?? message}
        </p>
      )}
    </div>
  );
}
