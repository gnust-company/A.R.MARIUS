import type { TFunction } from 'i18next';

/** A safe i18n key segment: the daemon's codes are snake_case, and anything else is a code this
 *  screen has never heard of rather than a path into the phrase table. */
export function segment(code: string): string {
  return /^[a-z0-9_]+$/.test(code) ? code : 'unknown';
}

/** Wall-clock time of one trace event, to the second. */
export function formatClock(iso?: string | null): string {
  if (!iso) return '';
  return new Date(iso).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
}

/** "3 minutes ago" — the thread reads as a conversation, so it speaks in distances, not clocks. */
export function relativeTime(iso: string, t: TFunction): string {
  const minutes = Math.floor((Date.now() - new Date(iso).getTime()) / 60000);
  if (Number.isNaN(minutes)) return '';
  if (minutes < 1) return t('common.justNow');
  if (minutes < 60) return t('common.minutesAgo', { count: minutes });
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return t('common.hoursAgo', { count: hours });
  return t('common.daysAgo', { count: Math.floor(hours / 24) });
}
