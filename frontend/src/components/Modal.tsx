import { useEffect, useId, useRef } from 'react';
import { createPortal } from 'react-dom';
import { motion, AnimatePresence, useReducedMotion } from 'framer-motion';
import { X } from 'lucide-react';
import type { ReactNode } from 'react';
import { useTranslation } from 'react-i18next';
import { cn } from '@/lib/utils';

interface ModalProps {
  isOpen: boolean;
  onClose: () => void;
  title?: ReactNode;
  /** Mono, wide-tracked line above the title ("NEW SKILL · MARKDOWN"). */
  eyebrow?: ReactNode;
  children: ReactNode;
  footer?: ReactNode;
  maxWidth?: string;
  className?: string;
}

/**
 * The one dialog of the Đài quan sát design: rendered into `document.body` so no transformed
 * ancestor can clip it, a blurred veil over the page, an eyebrow + Lora title with a close
 * button, and a body that scrolls on its own. On a phone it becomes a bottom sheet that never
 * reaches past the top of the viewport.
 */
export default function Modal({ isOpen, onClose, title, eyebrow, children, footer, maxWidth = 'max-w-lg', className }: ModalProps) {
  const { t } = useTranslation();
  const titleId = useId();
  const reduceMotion = useReducedMotion();
  // Latest close handler, so the key listener does not need re-binding on every render.
  const close = useRef(onClose);
  useEffect(() => {
    close.current = onClose;
  }, [onClose]);

  useEffect(() => {
    if (!isOpen) return;
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape') close.current();
    };
    // Restore whatever the page had, so a dialog opened over another dialog does not unlock
    // scrolling underneath the first one when it closes.
    const previousOverflow = document.body.style.overflow;
    const previousFocus = document.activeElement as HTMLElement | null;
    document.addEventListener('keydown', handler);
    document.body.style.overflow = 'hidden';
    return () => {
      document.removeEventListener('keydown', handler);
      document.body.style.overflow = previousOverflow;
      previousFocus?.focus?.();
    };
  }, [isOpen]);

  return createPortal(
    <AnimatePresence>
      {isOpen && (
        <motion.div
          className="fixed inset-0 z-overlay flex items-end justify-center sm:items-center sm:p-6"
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          transition={{ duration: 0.18 }}
          onMouseDown={(e) => {
            if (e.target === e.currentTarget) onClose();
          }}
        >
          {/* Veil */}
          <div className="pointer-events-none absolute inset-0 bg-scrim/45 backdrop-blur-[6px]" aria-hidden />

          {/* Panel. `max-h` and the column keep the header — and its close button — inside
              the window however tall the body grows; only the body scrolls. */}
          <motion.section
            role="dialog"
            aria-modal="true"
            aria-labelledby={title ? titleId : undefined}
            className={cn(
              'relative z-modal flex w-full flex-col overflow-hidden border border-line-strong bg-surface shadow-[var(--shadow)]',
              'max-h-[calc(100dvh-28px)] rounded-t-xl border-b-0',
              'sm:max-h-[min(880px,calc(100dvh-48px))] sm:rounded-xl sm:border-b',
              maxWidth,
              className
            )}
            initial={reduceMotion ? { opacity: 0 } : { opacity: 0, y: 24, scale: 0.97 }}
            animate={reduceMotion ? { opacity: 1 } : { opacity: 1, y: 0, scale: 1 }}
            exit={reduceMotion ? { opacity: 0 } : { opacity: 0, y: 12, scale: 0.98 }}
            transition={reduceMotion ? { duration: 0.01 } : { duration: 0.26, ease: [0.2, 1, 0.2, 1] }}
          >
            {title ? (
              <header className="flex shrink-0 items-start justify-between gap-5 border-b border-line px-[18px] pb-[15px] pt-[19px] sm:px-6 sm:pb-[18px] sm:pt-[22px]">
                <div className="min-w-0">
                  {eyebrow && <p className="eyebrow">{eyebrow}</p>}
                  <h2
                    id={titleId}
                    className={cn(
                      'font-display text-[25px] font-normal leading-[1.16] tracking-[-0.02em] text-ink-strong break-words sm:text-[28px]',
                      eyebrow && 'mt-1.5'
                    )}
                  >
                    {title}
                  </h2>
                </div>
                <button
                  type="button"
                  onClick={onClose}
                  className="-mr-2 inline-flex h-11 w-11 shrink-0 items-center justify-center rounded-md text-ink-muted transition-colors hover:bg-surface-hover hover:text-ink-strong"
                  aria-label={t('common.closeDialog')}
                >
                  <X className="h-5 w-5" />
                </button>
              </header>
            ) : (
              <button
                type="button"
                onClick={onClose}
                className="absolute right-3 top-3 z-10 inline-flex h-11 w-11 items-center justify-center rounded-md text-ink-muted transition-colors hover:bg-surface-hover hover:text-ink-strong"
                aria-label={t('common.closeDialog')}
              >
                <X className="h-5 w-5" />
              </button>
            )}

            {/* Body */}
            <div className="min-h-0 flex-1 overflow-y-auto overscroll-contain px-[18px] py-[19px] sm:p-6">{children}</div>

            {/* Footer */}
            {footer && (
              <div className="flex shrink-0 flex-wrap justify-end gap-2.5 border-t border-line px-[18px] pb-[calc(16px+env(safe-area-inset-bottom))] pt-4 sm:px-6 sm:pb-5">
                {footer}
              </div>
            )}
          </motion.section>
        </motion.div>
      )}
    </AnimatePresence>,
    document.body
  );
}
