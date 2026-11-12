import { useState, type ReactNode } from 'react';
import { Link } from 'react-router';
import { useTranslation } from 'react-i18next';
import { ArrowUpRight, CheckCircle2, ThumbsDown } from 'lucide-react';

import StatusChip from '@/components/StatusChip';
import { signTaskApproval, type InboxItemDTO } from '@/lib/api';
import { errorText } from '@/lib/errors';
import { cn, wsHref } from '@/lib/utils';
import type { Project } from '@/store/appStore';

import AttemptDossier from './AttemptDossier';
import EscalationActions from './EscalationActions';
import { relativeTime } from './inbox-utils';
import OutputEvidence from './OutputEvidence';
import PhaseDecisionActions from './PhaseDecisionActions';

interface Props {
  item: InboxItemDTO;
  project?: Project;
  /** Shown when the project is not in the store any more. */
  projectName: string;
  /** The task's human code ("ACME-12"), once its project's tasks are loaded. */
  taskCode?: string;
  workspaceId?: string;
  frozen: boolean;
  busy: boolean;
  setBusy: (id: string | null) => void;
  onError: (message: string | null) => void;
  onDone: () => void;
}

function InfoCell({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="min-w-0 bg-surface px-3.5 py-3">
      <dt className="font-body text-body-xs text-ink-muted">{label}</dt>
      <dd className="mt-0.5 min-w-0 break-words font-body text-body-sm text-ink">{children}</dd>
    </div>
  );
}

/** Signing off a task's output from the inbox — the letter closes on its own because the
 *  thing it waited for has happened. */
function OutputAcceptanceActions({
  item,
  frozen,
  busy,
  setBusy,
  onError,
  onDone,
}: Pick<Props, 'item' | 'frozen' | 'busy' | 'setBusy' | 'onError' | 'onDone'>) {
  const { t } = useTranslation();
  const [reason, setReason] = useState('');
  const said = reason.trim();

  const sign = async (approve: boolean) => {
    if (!item.task_id) return;
    // Sending back without saying why leaves the worker nothing to fix (FR-040).
    if (!approve && !said) return;
    setBusy(item.id);
    try {
      await signTaskApproval(item.task_id, approve, approve ? undefined : said);
      setReason('');
      onDone();
    } catch (e) {
      onError(errorText(e, t));
    }
    setBusy(null);
  };

  return (
    <div className="mt-6">
      <label className="block font-body text-body-sm font-semibold text-ink-strong" htmlFor={`send-back-${item.id}`}>
        {t('inbox.sendBackReason')}{' '}
        <span className="font-normal text-ink-muted">({t('inbox.sendBackReasonHint')})</span>
      </label>
      <textarea
        id={`send-back-${item.id}`}
        className="field mt-2 resize-y py-2.5"
        rows={4}
        value={reason}
        maxLength={2000}
        disabled={frozen}
        placeholder={t('inbox.sendBackPlaceholder')}
        data-testid="inbox-send-back-reason"
        onChange={(e) => setReason(e.target.value)}
      />
      <div className="mt-4 flex flex-wrap items-center gap-2">
        <button
          className="btn btn-primary"
          disabled={busy || frozen}
          data-testid="inbox-accept"
          onClick={() => void sign(true)}
        >
          <CheckCircle2 className="w-4 h-4" aria-hidden /> {t('inbox.accept')}
        </button>
        <button
          className="btn btn-secondary"
          disabled={busy || frozen || !said}
          data-testid="inbox-send-back"
          onClick={() => void sign(false)}
        >
          <ThumbsDown className="w-4 h-4" aria-hidden /> {t('inbox.sendBack')}
        </button>
      </div>
    </div>
  );
}

/**
 * The open letter: what it is, where it comes from, what the system already tried, and the
 * answers the patron can give right here. Every action is the same server call the inbox
 * made before the redesign; only where it sits has changed.
 */
export default function InboxDetail({
  item,
  project,
  projectName,
  taskCode,
  workspaceId,
  frozen,
  busy,
  setBusy,
  onError,
  onDone,
}: Props) {
  const { t } = useTranslation();
  const pending = item.status === 'pending';
  const kindLabel = t(`inbox.kind.${item.kind}`, { defaultValue: item.kind });

  return (
    <article className="surface min-w-0 p-5 sm:p-7" aria-labelledby={`inbox-detail-${item.id}`}>
      <p className="eyebrow break-words">
        {kindLabel} · {project?.key ?? projectName}
      </p>
      <h2
        id={`inbox-detail-${item.id}`}
        className="mt-2 break-words font-display text-[24px] font-normal leading-[1.15] tracking-[-0.02em] text-ink-strong sm:text-[29px]"
      >
        {item.title}
      </h2>

      {(pending && item.reminder_tier > 0) || item.status === 'resolved' || item.status === 'void' || frozen ? (
        <div className="mt-3 flex flex-wrap items-center gap-2">
          {/* How many times it has been chased only matters while it still waits. */}
          {pending && item.reminder_tier > 0 && (
            <StatusChip status="checking" showDot={false} label={t('inbox.reminderTier', { tier: item.reminder_tier })} />
          )}
          {item.status === 'resolved' && <StatusChip status="done" label={t('inbox.handled')} />}
          {(item.status === 'void' || frozen) && (
            <span className="status-pill" data-testid="inbox-closed-badge">
              {t('inbox.closedProject')}
            </span>
          )}
        </div>
      ) : null}

      {item.body && (
        <p className="mt-3 whitespace-pre-line break-words font-body text-[14px] leading-[1.75] text-ink-light">
          {item.body}
        </p>
      )}

      <dl className="mt-6 grid grid-cols-2 gap-px overflow-hidden rounded-md border border-line bg-line sm:grid-cols-4">
        <InfoCell label={t('inbox.info.project')}>{projectName}</InfoCell>
        <InfoCell label={t('inbox.info.task')}>
          {item.task_id ? (
            <span className="task-code">{taskCode ?? '—'}</span>
          ) : (
            <span className="text-ink-light">{t('inbox.projectLevel')}</span>
          )}
        </InfoCell>
        <InfoCell label={t('inbox.info.arrived')}>{relativeTime(item.created_at, t) || '—'}</InfoCell>
        {pending ? (
          <InfoCell label={t('inbox.info.reminders')}>
            {item.reminder_tier > 0
              ? t('inbox.reminderTier', { tier: item.reminder_tier })
              : t('inbox.info.notReminded')}
          </InfoCell>
        ) : (
          <InfoCell label={t('inbox.info.resolvedAt')}>{relativeTime(item.resolved_at, t) || '—'}</InfoCell>
        )}
      </dl>

      {item.task_id && (
        <Link
          to={wsHref(workspaceId, `/tasks/${item.task_id}`)}
          className="btn-text mt-2"
          data-testid="inbox-open-task"
        >
          {t('inbox.open')} <ArrowUpRight className="h-4 w-4" aria-hidden />
        </Link>
      )}

      {/* The record of what was already tried (FR-061). Without it an escalation asks the
          patron to go and reconstruct the history before they can answer. */}
      {item.kind === 'escalation' && <AttemptDossier item={item} />}

      {item.kind === 'output_acceptance' && item.task_id && (
        <OutputEvidence key={item.task_id} taskId={item.task_id} workspaceId={workspaceId} />
      )}

      {pending && item.kind === 'output_acceptance' && item.task_id && (
        <OutputAcceptanceActions
          item={item}
          frozen={frozen}
          busy={busy}
          setBusy={setBusy}
          onError={onError}
          onDone={onDone}
        />
      )}

      {pending && item.kind === 'phase_decision' && (
        <PhaseDecisionActions
          item={item}
          frozen={frozen}
          busy={busy}
          setBusy={setBusy}
          onError={onError}
          onDone={onDone}
        />
      )}

      {pending && item.kind === 'escalation' && item.task_id && (
        <EscalationActions
          item={item}
          busy={busy}
          frozen={frozen}
          setBusy={setBusy}
          onError={onError}
          onDone={onDone}
        />
      )}

      {!pending && (
        <div
          className={cn(
            'mt-6 flex items-center gap-3 rounded-md border px-4 py-3.5',
            item.status === 'resolved' ? 'border-success/35 text-success' : 'border-line text-ink-muted'
          )}
        >
          <CheckCircle2 className="h-5 w-5 shrink-0" aria-hidden />
          <div className="min-w-0 font-body">
            <strong className="block text-body-md font-semibold">
              {item.status === 'resolved' ? t('inbox.resolvedStamp') : t('inbox.closedProject')}
            </strong>
            {item.resolved_at && (
              <span className="block text-body-xs text-ink-muted">{relativeTime(item.resolved_at, t)}</span>
            )}
          </div>
        </div>
      )}
    </article>
  );
}
