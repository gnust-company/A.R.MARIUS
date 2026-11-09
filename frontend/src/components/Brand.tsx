import { cn } from '@/lib/utils';

/** The Armarius sigil: a small planet held by two crossed orbits, in gold (DESIGN §3.1). */
export function Sigil({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 40 40" aria-hidden="true" className={cn('w-9 h-9 text-gold', className)}>
      <g fill="none" stroke="currentColor" strokeWidth="1">
        <ellipse cx="20" cy="20" rx="16" ry="7" transform="rotate(32 20 20)" opacity=".55" />
        <ellipse cx="20" cy="20" rx="16" ry="7" transform="rotate(-32 20 20)" opacity=".55" />
        <circle cx="20" cy="20" r="7.5" strokeWidth="1.2" />
      </g>
      <circle cx="20" cy="4.5" r="1.8" fill="currentColor" />
    </svg>
  );
}

/** Sigil + wordmark. `compact` drops the wordmark (the icon rail has room for the mark only). */
export function Brand({
  compact,
  subtitle = 'Agent atelier',
  className,
}: {
  compact?: boolean;
  subtitle?: string | null;
  className?: string;
}) {
  return (
    <span className={cn('inline-flex items-center gap-3 min-w-0', className)}>
      <Sigil />
      {!compact && (
        <span className="min-w-0 leading-none">
          <span className="block font-display text-[18px] font-medium tracking-[0.16em] text-ink-strong">
            ARMARIUS
          </span>
          {subtitle && (
            <span className="block mt-1 font-mono text-[9px] uppercase tracking-[0.17em] text-ink-muted whitespace-nowrap">
              {subtitle}
            </span>
          )}
        </span>
      )}
    </span>
  );
}
