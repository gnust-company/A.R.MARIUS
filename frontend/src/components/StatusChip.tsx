import { cn } from '@/lib/utils';

interface StatusChipProps {
  status: string;
  label?: string;
  showDot?: boolean;
  size?: 'sm' | 'md';
}

const STATUS_COLORS: Record<string, { bg: string; text: string; dot: string }> = {
  // Agent status
  online: { bg: 'bg-[#D8EADD]', text: 'text-[#2A6E3A]', dot: 'bg-status-online' },
  working: { bg: 'bg-[#F5E8CC]', text: 'text-[#8B6A28]', dot: 'bg-status-working' },
  idle: { bg: 'bg-[#E8E0D8]', text: 'text-[#8B7A6A]', dot: 'bg-status-idle' },
  offline: { bg: 'bg-[#E8E0D8]', text: 'text-[#8B7A6A]', dot: 'bg-status-offline' },
  hung: { bg: 'bg-[#F5DDD6]', text: 'text-[#8B3A28]', dot: 'bg-status-hung' },
  checking: { bg: 'bg-[#F5DDD6]', text: 'text-[#B84A32]', dot: 'bg-status-checking' },
  pending: { bg: 'bg-[#F5E8CC]', text: 'text-[#8B6A28]', dot: 'bg-status-pending' },
  invited: { bg: 'bg-[#E8E0D8]', text: 'text-[#8B7A6A]', dot: 'bg-status-invited' },
  revoked: { bg: 'bg-[#E8E0D8]', text: 'text-[#8B7A6A]', dot: 'bg-status-revoked' },
  // Project status
  setup: { bg: 'bg-[#F5DDD6]', text: 'text-[#B84A32]', dot: 'bg-[#B84A32]' },
  active: { bg: 'bg-[#D8EADD]', text: 'text-[#2A6E3A]', dot: 'bg-[#2A6E3A]' },
  archived: { bg: 'bg-[#E8E0D8]', text: 'text-[#8B7A6A]', dot: 'bg-[#8B7A6A]' },
  // Task status
  draft: { bg: 'bg-[#F5E8CC]', text: 'text-[#8B6A28]', dot: 'bg-[#8B6A28]' },
  backlog: { bg: 'bg-[#EDE4CE]', text: 'text-[#6B5E4E]', dot: 'bg-[#6B5E4E]' },
  todo: { bg: 'bg-[#E8DED0]', text: 'text-[#6B5E4E]', dot: 'bg-[#6B5E4E]' },
  in_progress: { bg: 'bg-[#D4E8F0]', text: 'text-[#2A5A6E]', dot: 'bg-[#2A5A6E]' },
  blocked: { bg: 'bg-[#F5DDD6]', text: 'text-[#8B3A28]', dot: 'bg-[#8B3A28]' },
  in_review: { bg: 'bg-[#F5E8CC]', text: 'text-[#8B6A28]', dot: 'bg-[#8B6A28]' },
  done: { bg: 'bg-[#D8EADD]', text: 'text-[#2A6E3A]', dot: 'bg-[#2A6E3A]' },
  cancelled: { bg: 'bg-[#E8E0D8]', text: 'text-[#8B7A6A]', dot: 'bg-[#8B7A6A]' },
};

export default function StatusChip({ status, label, showDot = true, size = 'sm' }: StatusChipProps) {
  const colors = STATUS_COLORS[status] || STATUS_COLORS.offline;
  const displayLabel = label || status.replace(/_/g, ' ');

  return (
    <span
      className={cn(
        'inline-flex items-center gap-1 rounded-full font-body font-medium capitalize',
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
