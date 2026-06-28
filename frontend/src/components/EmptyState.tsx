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
        'border border-dashed border-vellum-dark rounded-lg',
        className
      )}
    >
      <Icon className="w-12 h-12 text-ink-muted mb-4" strokeWidth={1.5} />
      <h3 className="font-display text-display-sm text-ink mb-2">{title}</h3>
      <p className="font-body text-body-md text-ink-light max-w-sm mb-6">{description}</p>
      {action}
    </div>
  );
}
