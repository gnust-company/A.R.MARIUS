import { cn } from '@/lib/utils';

interface StatusChipProps {
  status: string;
  label?: string;
  showDot?: boolean;
  size?: 'sm' | 'md';
}

// One meaning per colour (see tailwind.config.js): lapis = running, verdigris = alive/done,
// gold = waiting on the patron, vermilion = blocked/broken, ash = resting/not started.
const LAPIS = { bg: 'bg-lapis-bg', text: 'text-lapis-ink', dot: 'bg-lapis' };
const VERDIGRIS = { bg: 'bg-verdigris-bg', text: 'text-verdigris-ink', dot: 'bg-verdigris' };
const GOLD = { bg: 'bg-gold-bg', text: 'text-gold-ink', dot: 'bg-gold' };
const VERMILION = { bg: 'bg-vermilion-bg', text: 'text-vermilion-ink', dot: 'bg-vermilion' };
const ASH = { bg: 'bg-ash-bg', text: 'text-ink-light', dot: 'bg-ash' };

const STATUS_COLORS: Record<string, { bg: string; text: string; dot: string }> = {
  // Agent status
  online: VERDIGRIS,
  working: LAPIS,
  idle: ASH,
  offline: ASH,
  hung: VERMILION,
  checking: GOLD,
  // Project phase (spec 001): setup → planning → operating ⇄ maintaining → closed
  setup: GOLD,
  planning: GOLD,
  operating: VERDIGRIS,
  maintaining: LAPIS,
  closed: ASH,
  // Task status
  draft: ASH,
  backlog: ASH,
  todo: ASH,
  in_progress: LAPIS,
  blocked: VERMILION,
  in_review: GOLD,
  done: VERDIGRIS,
  cancelled: ASH,
};

export default function StatusChip({ status, label, showDot = true, size = 'sm' }: StatusChipProps) {
  const colors = STATUS_COLORS[status] || STATUS_COLORS.offline;
  const raw = label || status.replace(/_/g, ' ');
  // Sentence case, not `capitalize`: Title Case on every word reads wrong in Vietnamese.
  const displayLabel = raw.charAt(0).toUpperCase() + raw.slice(1);

  return (
    <span
      className={cn(
        'inline-flex items-center gap-1 rounded-full font-body font-medium whitespace-nowrap',
        size === 'sm' && 'px-2 py-0.5 text-body-xs',
        size === 'md' && 'px-3 py-1 text-body-sm',
        colors.bg,
        colors.text
      )}
    >
      {showDot && (
        <span className={cn('w-1.5 h-1.5 rounded-full', colors.dot)} />
      )}
      {displayLabel}
    </span>
  );
}
