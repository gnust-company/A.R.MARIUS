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
        // A quiet card of the Đài quan sát design (`.surface`); hover only firms up the hairline.
        'surface p-6',
        (hover || largeHover) && 'transition-colors hover:border-line-strong',
        deckle && 'deckle',
        className
      )}
      {...props}
    >
      {children}
    </Tag>
  );
}
