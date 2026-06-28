import { cn } from '@/lib/utils';

interface DropCapProps {
  text: string;
  className?: string;
}

export default function DropCap({ text, className }: DropCapProps) {
  return (
    <span
      className={cn(
        'dropcap font-display text-ink inline-block',
        className
      )}
    >
      {text}
    </span>
  );
}
