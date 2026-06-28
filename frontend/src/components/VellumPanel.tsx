import type { ReactNode, HTMLAttributes } from 'react';
import { cn } from '@/lib/utils';

interface VellumPanelProps extends HTMLAttributes<HTMLDivElement> {
  children: ReactNode;
  hover?: boolean;
  largeHover?: boolean;
  deckle?: boolean;
  as?: 'div' | 'article' | 'section';
}

export default function VellumPanel({
  children,
  hover = true,
  largeHover = false,
  deckle = false,
  as: Tag = 'div',
  className,
  ...props
}: VellumPanelProps) {
  return (
    <Tag
      className={cn(
        'bg-vellum-deep border border-vellum-dark rounded-md p-6',
        hover && 'gilt',
        largeHover && 'gilt-lg',
        deckle && 'deckle',
        className
      )}
      {...props}
    >
      {children}
    </Tag>
  );
}
