import { useEffect, useId, type ReactNode } from 'react';
import { createPortal } from 'react-dom';
import { motion, useReducedMotion } from 'framer-motion';
import { X } from 'lucide-react';
import { useTranslation } from 'react-i18next';

/**
 * A dialog portalled to `document.body` (DESIGN §7): nothing in the page's stacking contexts —
 * the scene panel, the phone's bottom navigation — can sit on top of it or clip it.
 * Render it inside `<AnimatePresence>` for the exit fade.
 */
export default function PortalModal({
  title,
  eyebrow,
  onClose,
  children,
}: {
  title: string;
  eyebrow?: ReactNode;
  onClose: () => void;
  children: ReactNode;
}) {
  const { t } = useTranslation();
  const titleId = useId();
  const reduceMotion = useReducedMotion();

  useEffect(() => {
    const previous = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onClose();
    };
    window.addEventListener('keydown', onKey);
    return () => {
      document.body.style.overflow = previous;
      window.removeEventListener('keydown', onKey);
    };
  }, [onClose]);

  return createPortal(
    <motion.div
      className="fixed inset-0 z-modal flex items-end justify-center bg-scrim/45 p-3 backdrop-blur-sm sm:items-center sm:p-6"
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      exit={{ opacity: 0 }}
      transition={{ duration: reduceMotion ? 0.01 : 0.18 }}
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}
    >
      <motion.section
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        className="flex max-h-[calc(100dvh-24px)] w-full max-w-[700px] flex-col overflow-hidden rounded-xl border border-line bg-surface shadow-gilt sm:max-h-[calc(100dvh-48px)]"
        initial={reduceMotion ? { opacity: 0 } : { opacity: 0, y: 24, scale: 0.97 }}
        animate={reduceMotion ? { opacity: 1 } : { opacity: 1, y: 0, scale: 1 }}
        exit={reduceMotion ? { opacity: 0 } : { opacity: 0, y: 12, scale: 0.98 }}
        transition={reduceMotion ? { duration: 0.01 } : { duration: 0.26, ease: [0.2, 1, 0.2, 1] }}
      >
        <header className="flex shrink-0 items-start justify-between gap-4 border-b border-line px-5 pb-4 pt-5 sm:px-6">
          <div className="min-w-0">
            {eyebrow && <p className="eyebrow">{eyebrow}</p>}
            <h2 id={titleId} className="mt-1.5 truncate font-display text-display-md text-ink-strong">
              {title}
            </h2>
          </div>
          <button
            type="button"
            autoFocus
            onClick={onClose}
            aria-label={t('common.closeDialog')}
            className="grid h-10 w-10 shrink-0 place-items-center rounded-md text-ink-light transition-colors hover:bg-surface-hover hover:text-ink-strong"
          >
            <X className="h-5 w-5" aria-hidden />
          </button>
        </header>
        <div className="min-h-0 overflow-y-auto px-5 pb-6 pt-5 sm:px-6">{children}</div>
      </motion.section>
    </motion.div>,
    document.body,
  );
}
