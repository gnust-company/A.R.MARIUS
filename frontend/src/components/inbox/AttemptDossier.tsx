import { useTranslation } from 'react-i18next';

import type { InboxItemDTO } from '@/lib/api';
import { stallText } from '@/lib/stall';

import { relativeTime } from './inbox-utils';

/** The record of what the system already tried, on an escalation (FR-061).
 *
 * A patron asked "this is stuck, what now?" has to go and reconstruct the history before
 * they can answer. One told "re-woken three times, the Leader was asked, still stuck, here
 * is the question" answers in one read. That gap is what decides whether an escalation is
 * cleared today or next week.
 *
 * Every field is optional on purpose: the dossier is written by the escalator and read
 * here, and a UI that threw on a missing key would take the whole inbox down over a shape
 * change in a background loop.
 *
 * It lives in the detail panel, where only one letter is open at a time, so the history is
 * laid out in full rather than folded away. */
export default function AttemptDossier({ item }: { item: InboxItemDTO }) {
  const { t } = useTranslation();
  const d = (item.attempt_dossier ?? {}) as Record<string, unknown>;
  const cause = typeof d.cause === 'string' ? d.cause : undefined;
  const attempts = typeof d.level1_attempts === 'number' ? d.level1_attempts : 0;
  const leaderAsked = d.leader_asked === true;
  const question = typeof d.question === 'string' ? d.question : undefined;
  const lastAttempt = typeof d.last_attempt_at === 'string' ? d.last_attempt_at : undefined;

  if (!cause && !attempts && !leaderAsked && !question) return null;
  const tried = Boolean(cause || attempts || leaderAsked);

  return (
    <>
      {tried && (
        <section className="mt-6 border-y border-line py-4" data-testid="inbox-dossier">
          <h3 className="font-body text-body-sm font-semibold text-ink-strong">{t('inbox.dossier.title')}</h3>
          <ul className="mt-2.5 flex flex-col gap-2 font-body text-body-sm text-ink-light">
            {cause && (
              <li className="grid grid-cols-1 gap-x-4 gap-y-0.5 sm:grid-cols-[minmax(0,1fr)_minmax(0,1.4fr)]">
                <span className="text-ink-muted">{t('inbox.dossier.cause')}</span>
                <span className="min-w-0 break-words text-ink">{stallText(cause, t) ?? t('board.stalled')}</span>
              </li>
            )}
            {attempts > 0 && <li>{t('inbox.dossier.attempts', { count: attempts })}</li>}
            {leaderAsked && <li>{t('inbox.dossier.leaderAsked')}</li>}
            {lastAttempt && (
              <li className="text-ink-muted">{t('inbox.dossier.lastAttempt', { when: relativeTime(lastAttempt, t) })}</li>
            )}
          </ul>
        </section>
      )}
      {/* The question is what the patron is being asked to decide, so it gets the gold. */}
      {question && (
        <section className="mt-6 rounded-md border border-gold/40 bg-gold-soft px-4 py-3.5">
          <h3 className="eyebrow text-gold">{t('inbox.dossier.question')}</h3>
          <p className="mt-1.5 font-body text-body-md text-ink-strong whitespace-pre-line break-words">{question}</p>
        </section>
      )}
    </>
  );
}
