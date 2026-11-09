import { cn } from '@/lib/utils';

interface StatusChipProps {
  status: string;
  label?: string;
  showDot?: boolean;
  size?: 'sm' | 'md';
}

// One meaning per colour (DESIGN §3.3): gold = working / waiting on the patron, success = alive or
// done, warning = being checked, danger = blocked or broken, sapphire = in review, faint = resting.
// The pill always carries a word as well as the colour, so state never rides on colour alone.
const GOLD = { text: 'text-gold', border: 'border-gold/35', dot: 'bg-gold' };
const SUCCESS = { text: 'text-success', border: 'border-success/35', dot: 'bg-success' };
const WARNING = { text: 'text-warning', border: 'border-warning/35', dot: 'bg-warning' };
const DANGER = { text: 'text-danger', border: 'border-danger/35', dot: 'bg-danger' };
const SAPPHIRE = { text: 'text-sapphire-strong', border: 'border-sapphire/35', dot: 'bg-sapphire' };
const FAINT = { text: 'text-ink-muted', border: 'border-line-strong', dot: 'bg-ink-faint' };

const STATUS_COLORS: Record<string, { text: string; border: string; dot: string }> = {
  // Agent status
  online: SUCCESS,
  working: GOLD,
  idle: SUCCESS,
  offline: FAINT,
  hung: DANGER,
  checking: WARNING,
  // Project phase (spec 001): setup → planning → operating ⇄ maintaining → closed
  setup: GOLD,
  planning: GOLD,
  operating: SUCCESS,
  maintaining: SAPPHIRE,
  closed: FAINT,
  // Task status
  draft: FAINT,
  backlog: FAINT,
  todo: FAINT,
  in_progress: GOLD,
  blocked: DANGER,
  in_review: SAPPHIRE,
  done: SUCCESS,
  cancelled: FAINT,
};

export default function StatusChip({ status, label, showDot = true, size = 'sm' }: StatusChipProps) {
  const colors = STATUS_COLORS[status] || STATUS_COLORS.offline;
  const raw = label || status.replace(/_/g, ' ');
  // Sentence case, not `capitalize`: Title Case on every word reads wrong in Vietnamese.
  const displayLabel = raw.charAt(0).toUpperCase() + raw.slice(1);

  return (
    <span
      className={cn(
        'inline-flex items-center gap-1.5 rounded-full border bg-transparent font-body whitespace-nowrap',
        size === 'sm' && 'min-h-[22px] px-2 text-[11px]',
        size === 'md' && 'min-h-[26px] px-2.5 text-body-sm',
        colors.border,
        colors.text
      )}
    >
      {showDot && (
        <span className={cn('w-[7px] h-[7px] rounded-full', colors.dot)} />
      )}
      {displayLabel}
    </span>
  );
}
