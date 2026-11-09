import type { TFunction } from 'i18next';
import {
  AlertTriangle,
  CheckCircle2,
  FileQuestion,
  GitBranch,
  ScrollText,
  type LucideIcon,
} from 'lucide-react';

import type { InboxItemDTO } from '@/lib/api';

/** The server files each letter under a kind; each kind has its own mark. */
const KIND_ICON: Record<string, LucideIcon> = {
  output_acceptance: CheckCircle2,
  plan_approval: ScrollText,
  major_change_approval: GitBranch,
  phase_decision: GitBranch,
  escalation: AlertTriangle,
  question: FileQuestion,
};

export function kindIcon(kind: string): LucideIcon {
  return KIND_ICON[kind] ?? FileQuestion;
}

/** Decisions about direction (a plan, a big change, a phase) carry the patron's gold. */
const DIRECTION_KINDS = new Set(['plan_approval', 'major_change_approval', 'phase_decision']);

/** Colour of a letter's mark. An escalation is something already stuck, so it reads as
 *  danger; a call about direction is gold; a sign-off or a question is sapphire. A letter
 *  that is no longer waiting goes quiet. */
export function kindTone(item: InboxItemDTO): string {
  if (item.status !== 'pending') return 'text-ink-muted';
  if (item.kind === 'escalation') return 'text-danger';
  if (DIRECTION_KINDS.has(item.kind)) return 'text-gold';
  return 'text-sapphire-strong';
}

export function relativeTime(iso: string | null | undefined, t: TFunction): string {
  if (!iso) return '';
  const minutes = Math.floor((Date.now() - new Date(iso).getTime()) / 60000);
  if (minutes < 1) return t('common.justNow');
  if (minutes < 60) return t('common.minutesAgo', { count: minutes });
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return t('common.hoursAgo', { count: hours });
  return t('common.daysAgo', { count: Math.floor(hours / 24) });
}
