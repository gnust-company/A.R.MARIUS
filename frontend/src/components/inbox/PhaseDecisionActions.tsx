import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Archive, Layers, Wrench } from 'lucide-react';

import { changeProjectPhase, resolveInboxItem, type InboxItemDTO } from '@/lib/api';
import { errorText } from '@/lib/errors';

interface Props {
  item: InboxItemDTO;
  frozen: boolean;
  busy: boolean;
  setBusy: (id: string | null) => void;
  onError: (message: string | null) => void;
  onDone: () => void;
}

/** The three answers a finished batch offers, as the server names them (FR-043). */
const CLOSE = 'dong_du_an';
const MAINTAIN = 'chuyen_bao_tri';
const NEW_BATCH = 'mo_dot_moi';

/**
 * The patron's answer to "this batch is done — what now?" (FR-043).
 *
 * The letter arrived carrying three choices and the screen drew none of them: it could be
 * read and never answered, and nothing else in the interface closed a project either — the
 * call for it existed and had no caller (found 2026-11-12, on the first batch a real team
 * finished). So the letter sat in the waiting list for good.
 *
 * Only the choices the letter itself carries are offered. A phase letter without them is the
 * Leader *proposing* a move, which names its target in prose and is answered on the project.
 *
 * Closing is the one answer that cannot be taken back, so it takes two presses.
 */
export default function PhaseDecisionActions({ item, frozen, busy, setBusy, onError, onDone }: Props) {
  const { t } = useTranslation();
  const [confirmingClose, setConfirmingClose] = useState(false);

  const offered = Array.isArray(item.attempt_dossier?.choices)
    ? (item.attempt_dossier.choices as unknown[]).filter((c): c is string => typeof c === 'string')
    : [];
  if (!item.project_id || offered.length === 0) return null;
  const projectId = item.project_id;

  const decide = async (choice: string) => {
    setBusy(item.id);
    onError(null);
    try {
      if (choice === CLOSE) await changeProjectPhase(projectId, 'closed');
      else if (choice === MAINTAIN) await changeProjectPhase(projectId, 'maintaining');
      // A new batch changes no phase: the project stays in operation and the patron tells
      // the Leader what comes next. The letter is what gets answered.
      else await resolveInboxItem(item.id);
      onDone();
    } catch (e) {
      onError(errorText(e, t));
    }
    setBusy(null);
  };

  return (
    <div className="mt-6" data-testid="inbox-phase-decision">
      <p className="font-body text-body-sm font-semibold text-ink-strong">{t('inbox.phase.question')}</p>
      <div className="mt-3 flex flex-col gap-2">
        {offered.includes(NEW_BATCH) && (
          <button className="btn btn-secondary h-auto min-h-[44px] justify-start whitespace-normal py-2.5 text-left" disabled={busy || frozen} onClick={() => void decide(NEW_BATCH)}>
            <Layers className="h-4 w-4 shrink-0" aria-hidden />
            <span className="min-w-0 text-left">
              {t('inbox.phase.newBatch')}
              <span className="block font-normal text-ink-muted">{t('inbox.phase.newBatchHint')}</span>
            </span>
          </button>
        )}
        {offered.includes(MAINTAIN) && (
          <button className="btn btn-secondary h-auto min-h-[44px] justify-start whitespace-normal py-2.5 text-left" disabled={busy || frozen} onClick={() => void decide(MAINTAIN)}>
            <Wrench className="h-4 w-4 shrink-0" aria-hidden />
            <span className="min-w-0 text-left">
              {t('inbox.phase.maintain')}
              <span className="block font-normal text-ink-muted">{t('inbox.phase.maintainHint')}</span>
            </span>
          </button>
        )}
        {offered.includes(CLOSE) &&
          (confirmingClose ? (
            <div className="flex flex-wrap items-center gap-2 rounded-md border border-danger/40 px-3 py-2.5">
              <p className="min-w-0 flex-1 font-body text-body-sm text-ink">{t('inbox.phase.closeConfirm')}</p>
              <button className="btn btn-danger btn-sm" disabled={busy || frozen} onClick={() => void decide(CLOSE)}>
                {t('inbox.phase.closeYes')}
              </button>
              <button className="btn btn-secondary btn-sm" disabled={busy} onClick={() => setConfirmingClose(false)}>
                {t('common.cancel')}
              </button>
            </div>
          ) : (
            <button className="btn btn-secondary h-auto min-h-[44px] justify-start whitespace-normal py-2.5 text-left" disabled={busy || frozen} onClick={() => setConfirmingClose(true)}>
              <Archive className="h-4 w-4 shrink-0" aria-hidden />
              <span className="min-w-0 text-left">
                {t('inbox.phase.close')}
                <span className="block font-normal text-ink-muted">{t('inbox.phase.closeHint')}</span>
              </span>
            </button>
          ))}
      </div>
    </div>
  );
}
