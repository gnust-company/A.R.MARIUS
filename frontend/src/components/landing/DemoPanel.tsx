import { useSyncExternalStore } from 'react';
import { motion, useReducedMotion } from 'framer-motion';
import { Check, ChevronRight, Inbox, Undo2 } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { cn } from '@/lib/utils';
import { DEMO_AGENT, DEMO_TASK_TITLES, PHASE_MS, demoTaskCode, type DemoPhase, type LandingDemo } from './landingDemo';

/*
 * The visitor's side of the landing demo: an inbox that stays empty while the agent works and
 * asks for a decision once the agent arrives. The scene behind the page reads the same
 * `LandingDemo`, so the figure in the Patron room and this card always tell the same story.
 *
 * Scripted data, and labelled as such on screen: nothing here talks to a workspace.
 */

/** Which of the three steps a phase belongs to. `approved` has passed all of them. */
const STEP_OF: Record<DemoPhase, number> = { idle: -1, claim: 0, work: 1, returned: 1, walk: 2, waiting: 2, approved: 3 };
const STEPS = ['step1', 'step2', 'step3'] as const;

export default function DemoPanel({ demo }: { demo: LandingDemo }) {
  const { t } = useTranslation();
  const reduced = useReducedMotion();
  const { phase, task, revision, approved, sentBack } = useSyncExternalStore(demo.subscribe, demo.getSnapshot, demo.getSnapshot);
  const waiting = phase === 'waiting';
  const working = phase === 'work';
  const step = STEP_OF[phase];
  const code = demoTaskCode(task);
  const title = t(`landing.demo.tasks.t${(task % DEMO_TASK_TITLES) + 1}`);
  const status = t(`landing.demo.status.${working && revision > 0 ? 'rework' : phase}`, { name: DEMO_AGENT, code });

  return (
    <div className="my-[30px] max-w-[560px]">
      <ol aria-label={t('landing.workflow.flowLabel')} className="flex flex-wrap items-center gap-x-2.5 gap-y-2 sm:gap-x-4">
        {STEPS.map((key, index) => {
          const done = step > index;
          const active = step === index;
          return (
            <li key={key} aria-current={active ? 'step' : undefined} className="flex items-center gap-2.5 sm:gap-4">
              {index > 0 && <ChevronRight className="h-[13px] w-[13px] text-ink-muted sm:h-[17px] sm:w-[17px]" aria-hidden />}
              <span className="grid gap-[7px]">
                <small className={cn('flex items-center gap-1 font-mono text-[9px]', active ? 'text-gold' : 'text-ink-muted')}>
                  0{index + 1}
                  {done && <Check className="h-2.5 w-2.5 text-success" strokeWidth={2.4} aria-hidden />}
                </small>
                <strong
                  className={cn(
                    'font-display text-[16px] font-normal transition-colors duration-300 motion-reduce:transition-none sm:text-[20px]',
                    active ? 'text-gold' : done ? 'text-ink-strong' : 'text-ink-muted'
                  )}
                >
                  {t(`landing.workflow.${key}`)}
                </strong>
              </span>
            </li>
          );
        })}
      </ol>

      <div
        className={cn(
          'mt-5 rounded-xl border bg-surface/90 shadow-soft backdrop-blur-md transition-colors duration-300 motion-reduce:transition-none',
          waiting ? 'border-gold' : 'border-line'
        )}
      >
        <div className="flex items-center justify-between gap-3 border-b border-line px-4 py-2.5">
          <span className="flex items-center gap-2 text-[12px] font-semibold text-ink-strong">
            <Inbox className="h-4 w-4 text-ink-light" strokeWidth={1.6} aria-hidden />
            {t('landing.demo.inbox')}
          </span>
          <span
            className={cn(
              'grid h-5 min-w-5 place-items-center rounded-full px-1.5 font-mono text-[10px]',
              waiting ? 'bg-gold text-canvas' : 'bg-line text-ink-muted'
            )}
          >
            <span aria-hidden>{waiting ? 1 : 0}</span>
            <span className="sr-only">{t('landing.demo.pending', { count: waiting ? 1 : 0 })}</span>
          </span>
        </div>

        <div className="flex items-start gap-3 px-4 pb-3 pt-3.5">
          <span aria-hidden className="grid h-9 w-9 shrink-0 place-items-center rounded-full border border-gold/60 bg-gold-soft font-display text-[16px] text-ink-strong">
            {DEMO_AGENT.charAt(0)}
          </span>
          <div className="min-w-0 flex-1">
            <p className="flex flex-wrap items-baseline gap-x-2 text-body-sm text-ink-strong">
              <span className="font-mono text-[10px] text-ink-muted">{code}</span>
              <strong className="font-semibold">{title}</strong>
            </p>
            <p className="mt-1 min-h-[2.9em] text-[12px] leading-[1.45] text-ink-light sm:min-h-[1.45em]">{status}</p>
            <div aria-hidden className="mt-2 h-[3px] overflow-hidden rounded-full bg-line">
              {working && (
                <motion.i
                  key={`${task}-${revision}`}
                  className="block h-full origin-left bg-sapphire"
                  initial={{ scaleX: reduced ? 1 : 0, opacity: reduced ? 0.5 : 1 }}
                  animate={{ scaleX: 1 }}
                  transition={{ duration: reduced ? 0 : PHASE_MS.work / 1000, ease: 'linear' }}
                />
              )}
              {step >= 2 && <i className={cn('block h-full', phase === 'approved' ? 'bg-success' : 'bg-gold')} />}
            </div>
          </div>
        </div>

        {/* Always in the DOM, so the keyboard focus survives a decision; inert until asked. */}
        <div className="flex flex-wrap items-center gap-2 border-t border-line px-4 py-3">
          <button
            type="button"
            aria-disabled={!waiting}
            onClick={() => demo.approve()}
            className={cn('btn btn-primary btn-sm', !waiting && 'cursor-default opacity-40')}
          >
            <Check className="h-4 w-4" aria-hidden />
            {t('landing.demo.approve')}
          </button>
          <button
            type="button"
            aria-disabled={!waiting}
            onClick={() => demo.sendBack()}
            className={cn('btn btn-secondary btn-sm', !waiting && 'cursor-default opacity-40')}
          >
            <Undo2 className="h-4 w-4" aria-hidden />
            {t('landing.demo.sendBack')}
          </button>
          <span className="ml-auto font-mono text-[10px] text-ink-muted">{t('landing.demo.counters', { approved, sentBack })}</span>
        </div>
      </div>

      {/* Announced only when a decision is asked for; the looping script itself stays quiet. */}
      <p aria-live="polite" className="sr-only">
        {waiting ? t('landing.demo.announce', { name: DEMO_AGENT, code }) : ''}
      </p>
      <p className="mt-3 flex items-center gap-2 font-mono text-[9px] uppercase tracking-[0.1em] text-ink-muted sm:text-[10px]">
        <i aria-hidden className="h-1.5 w-1.5 shrink-0 rounded-full bg-gold" />
        {t('landing.demo.label')}
      </p>
    </div>
  );
}
