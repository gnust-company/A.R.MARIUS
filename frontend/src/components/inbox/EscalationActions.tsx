import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { CheckCheck, PencilLine, UserPlus, XCircle } from 'lucide-react';

import Dropdown from '@/components/Dropdown';
import { answerInboxItem, listProjectAgents, type InboxItemDTO, type ProjectAgentDTO } from '@/lib/api';
import { errorText } from '@/lib/errors';
import { cn } from '@/lib/utils';

const fieldLabel = 'block font-body text-body-sm font-medium text-ink';

/** Answering an *escalation* in place, where it is asked (FR-061a).
 *
 * The ladder carries a dropped task up to the patron and then stops — past that point the
 * system has no move left. Yet the item used to carry a single *Open* button: it asked
 * three questions and offered none of the answers, so the reader had to go and find the
 * place to reply. That is the hard part, and handing it to the very person the ladder
 * exists to save time for only makes the net fall short later rather than never.
 *
 * Four ways out, and the fourth is a different kind of thing from the first three. Those
 * say *"system, do this for me"*; the fourth says *"I sorted it outside, carry on"* —
 * the patron restarted a hung agent, fixed something on their own machine. Without it
 * they must pretend to pick one of the other three.
 *
 * The thing to hold on to: **the letter closes because the patron answered it**. The
 * stall sweep never touches the inbox (FR-061b), and closing the letter is where the
 * system recomputes whether anything is still about to touch the task (FR-061c). Miss
 * that and the task leaves the net for good.
 *
 * All of which is one server call, not two (FR-061e). The patron made one decision, so it
 * lands as one fact: the server changes the task and closes the letter under a single
 * commit. Acting from here and closing separately would leave a window where the task
 * moved and the question still stood, and a patron who saw that failure and pressed again
 * would run the action twice — waking a new owner a second time for one incident.
 */
export default function EscalationActions({
  item,
  busy,
  frozen,
  setBusy,
  onError,
  onDone,
}: {
  item: InboxItemDTO;
  busy: boolean;
  /** Its project is closed: the letter stays, readable, but nothing on it can be acted
   *  on any more (FR-005). The server refuses these calls too — this only keeps the
   *  patron from being handed a button that answers 409. */
  frozen: boolean;
  setBusy: (id: string | null) => void;
  onError: (message: string | null) => void;
  onDone: () => void;
}) {
  const { t } = useTranslation();
  const [mode, setMode] = useState<'assign' | 'next' | 'cancel' | null>(null);
  const [agents, setAgents] = useState<ProjectAgentDTO[] | null>(null);
  const [agentId, setAgentId] = useState('');
  const [text, setText] = useState('');
  // The agent list is fetched only once the patron actually opens the *reassign* form.
  // Prefetching it for every item on mount is one request per item, most of them unused.
  useEffect(() => {
    if (mode !== 'assign' || agents !== null || !item.project_id) return;
    let alive = true;
    listProjectAgents(item.project_id)
      .then((rows) => {
        if (alive) setAgents(rows);
      })
      .catch((e: unknown) => {
        if (alive) onError(errorText(e, t));
      });
    return () => {
      alive = false;
    };
  }, [mode, agents, item.project_id, onError, t]);

  const close = () => {
    setMode(null);
    setAgentId('');
    setText('');
  };

  /** Send the patron's answer. One call: see the note on this component.
   *
   * `answerInboxItem` is also safe to repeat — an already-answered letter means the server
   * does nothing — so a patron who presses again after a network blip cannot act twice. */
  const run = async (
    answer: 'reassign' | 'next_action' | 'cancel' | 'handled',
    extra: { marius_id?: string; text?: string } = {},
  ) => {
    setBusy(item.id);
    onError(null);
    try {
      await answerInboxItem(item.id, { answer, ...extra });
      close();
      onDone();
    } catch (e) {
      onError(errorText(e, t));
    }
    setBusy(null);
  };

  const said = text.trim();

  if (mode === null) {
    return (
      <div className="mt-6 flex flex-wrap items-center gap-2">
        <button
          className="btn btn-secondary"
          disabled={busy || frozen}
          data-testid="escalation-reassign"
          onClick={() => setMode('assign')}
        >
          <UserPlus className="w-4 h-4" aria-hidden /> {t('inbox.escalation.reassign')}
        </button>
        <button
          className="btn btn-secondary"
          disabled={busy || frozen}
          data-testid="escalation-next-action"
          onClick={() => setMode('next')}
        >
          <PencilLine className="w-4 h-4" aria-hidden /> {t('inbox.escalation.changeNext')}
        </button>
        <button
          className="btn btn-danger"
          disabled={busy || frozen}
          data-testid="escalation-cancel-task"
          onClick={() => setMode('cancel')}
        >
          <XCircle className="w-4 h-4" aria-hidden /> {t('inbox.escalation.cancelTask')}
        </button>
        {/* Not disabled when frozen, unlike the three above it: this one writes nothing
            into the project, only into the patron's own inbox. Freezing it too is what
            once left letters that could never be cleared. */}
        <button
          className="btn btn-primary"
          disabled={busy}
          title={frozen ? t('inbox.closedProjectHint') : t('inbox.escalation.handledHint')}
          data-testid="escalation-handled"
          onClick={() => void run('handled')}
        >
          <CheckCheck className="w-4 h-4" aria-hidden /> {t('inbox.escalation.handled')}
        </button>
        <p className="basis-full font-body text-body-xs leading-relaxed text-ink-muted">
          {frozen ? (
            <span className="text-gold" data-testid="escalation-frozen-note">
              {t('inbox.closedProjectHint')}
            </span>
          ) : (
            t('inbox.escalation.handledHint')
          )}
        </p>
      </div>
    );
  }

  return (
    <div className="mt-6 flex flex-col gap-2 rounded-md border border-line bg-canvas-deep p-4">
      {mode === 'assign' && (
        <>
          <label className={fieldLabel}>{t('inbox.escalation.pickAgent')}</label>
          {agents !== null && agents.length === 0 ? (
            <p className="font-body text-body-sm text-ink-light">{t('inbox.escalation.noAgents')}</p>
          ) : (
            <Dropdown
              className="min-h-[44px] bg-field sm:max-w-sm"
              testId="escalation-agent-select"
              value={agentId}
              onChange={setAgentId}
              placeholder={agents === null ? t('common.loading') : t('inbox.escalation.pickAgent')}
              items={(agents ?? []).map((a) => ({ value: a.marius_id, label: a.name }))}
            />
          )}
        </>
      )}

      <label className={cn(fieldLabel, 'pt-1')} htmlFor={`escalation-text-${item.id}`}>
        {mode === 'assign'
          ? t('inbox.escalation.transferReason')
          : mode === 'next'
            ? t('inbox.escalation.nextAction')
            : t('inbox.escalation.cancelReason')}
      </label>
      <textarea
        id={`escalation-text-${item.id}`}
        className="field resize-y py-2.5"
        rows={3}
        value={text}
        // The server caps this at 2000 characters. Stopping it here means the writer
        // finds out while typing, rather than after a long paragraph and a bare 422.
        maxLength={2000}
        data-testid="escalation-text"
        placeholder={
          mode === 'assign'
            ? t('inbox.escalation.transferReasonPlaceholder')
            : mode === 'next'
              ? t('inbox.escalation.nextActionPlaceholder')
              : t('inbox.escalation.cancelReasonPlaceholder')
        }
        onChange={(e) => setText(e.target.value)}
      />

      <div className="flex flex-wrap items-center gap-2 pt-1">
        <button
          className={mode === 'cancel' ? 'btn btn-danger' : 'btn btn-primary'}
          data-testid="escalation-confirm"
          // All three paths want words, and not to be awkward: the new owner reads the
          // transfer reason, a cancelled task has to say why (FR-030), and an empty next
          // action is the same as changing nothing.
          disabled={busy || !said || (mode === 'assign' && !agentId)}
          onClick={() => {
            if (mode === 'assign') void run('reassign', { marius_id: agentId, text: said });
            else if (mode === 'next') void run('next_action', { text: said });
            else void run('cancel', { text: said });
          }}
        >
          {t('common.confirm')}
        </button>
        <button className="btn btn-ghost" disabled={busy} onClick={close}>
          {t('common.cancel')}
        </button>
      </div>
    </div>
  );
}
