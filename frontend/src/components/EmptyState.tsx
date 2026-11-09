import type { ReactNode } from 'react';
import type { LucideIcon } from 'lucide-react';
import { cn } from '@/lib/utils';

interface EmptyStateProps {
  icon: LucideIcon;
  title: string;
  description: string;
  action?: ReactNode;
  className?: string;
}

export default function EmptyState({ icon: Icon, title, description, action, className }: EmptyStateProps) {
  return (
    <div
      className={cn(
        'flex flex-col items-center justify-center text-center py-12 px-6',
        'border border-dashed border-line-strong rounded-lg',
        className
      )}
    >
      <span className="mb-4 flex h-14 w-14 items-center justify-center rounded-full border border-line bg-canvas-deep text-ink-muted">
        <Icon className="h-6 w-6" strokeWidth={1.5} aria-hidden />
      </span>
      <h3 className="mb-2 font-display text-display-sm text-ink-strong">{title}</h3>
      <p className={cn('max-w-sm font-body text-body-md text-ink-light', action && 'mb-6')}>{description}</p>
      {action}
    </div>
  );
}
