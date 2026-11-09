import { cn } from '@/lib/utils';

/** Liveness → dot colour. Working is gold, alive is green, checking amber, hung red, else faint. */
const DOT: Record<string, string> = {
  working: 'bg-gold',
  online: 'bg-success',
  idle: 'bg-success',
  checking: 'bg-warning',
  hung: 'bg-danger',
  stalled: 'bg-danger',
  offline: 'bg-ink-faint',
};

/** A tint per agent, picked from its name so the same agent keeps the same colour everywhere. */
const TINTS = ['var(--sapphire)', 'var(--gold)', 'var(--success)', '0.60 0.06 350', '0.62 0.08 200', '0.58 0.09 300'];

function tintFor(name: string) {
  let h = 0;
  for (const ch of name) h = (h * 31 + ch.charCodeAt(0)) >>> 0;
  return TINTS[h % TINTS.length];
}

/**
 * The agent's initial in a ringed circle (DESIGN avatar): a soft tint of the agent's colour,
 * an inner hairline ring, and a liveness dot at the bottom-right when `status` is given.
 */
export default function AgentAvatar({
  name,
  status,
  size = 'md',
  className,
}: {
  name: string;
  status?: string;
  size?: 'sm' | 'md' | 'lg';
  className?: string;
}) {
  const tint = tintFor(name || '?');
  return (
    <span
      className={cn(
        'relative inline-grid place-items-center shrink-0 rounded-full font-display text-ink-strong',
        size === 'sm' && 'w-8 h-8 text-[14px]',
        size === 'md' && 'w-[42px] h-[42px] text-[18px]',
        size === 'lg' && 'w-[58px] h-[58px] text-[25px]',
        className
      )}
      style={{
        border: `1px solid color-mix(in oklch, oklch(${tint}) 45%, oklch(var(--line)))`,
        background: `color-mix(in oklch, oklch(${tint}) 20%, oklch(var(--surface)))`,
      }}
      aria-hidden="true"
    >
      <span
        className="absolute inset-[4px] rounded-full"
        style={{ border: `1px solid color-mix(in oklch, oklch(${tint}) 32%, transparent)` }}
      />
      {(name || '?').charAt(0).toUpperCase()}
      {status && (
        <span
          className={cn(
            'absolute right-[-1px] bottom-[1px] rounded-full border-2 border-surface box-content',
            size === 'lg' ? 'w-[11px] h-[11px]' : 'w-[9px] h-[9px]',
            DOT[status] ?? DOT.offline
          )}
        />
      )}
    </span>
  );
}
