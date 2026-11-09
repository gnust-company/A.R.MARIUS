import { cn } from '@/lib/utils';

interface DropCapProps {
  text: string;
  className?: string;
}

/** Kept for callers from the earlier design. The editorial look no longer gilds a first
 *  letter, so this is just the text set in the display face. */
export default function DropCap({ text, className }: DropCapProps) {
  return <span className={cn('inline-block font-display font-normal text-ink-strong', className)}>{text}</span>;
}
