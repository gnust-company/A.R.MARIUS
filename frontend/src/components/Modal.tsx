import { useEffect, useRef } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { X } from 'lucide-react';
import type { ReactNode } from 'react';
import { useTranslation } from 'react-i18next';
import { cn } from '@/lib/utils';

interface ModalProps {
  isOpen: boolean;
  onClose: () => void;
  title?: ReactNode;
  children: ReactNode;
  footer?: ReactNode;
  maxWidth?: string;
  className?: string;
}

export default function Modal({ isOpen, onClose, title, children, footer, maxWidth = 'max-w-lg', className }: ModalProps) {
  const { t } = useTranslation();
  const overlayRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    if (isOpen) {
      document.addEventListener('keydown', handler);
      document.body.style.overflow = 'hidden';
    }
    return () => {
      document.removeEventListener('keydown', handler);
      document.body.style.overflow = '';
    };
  }, [isOpen, onClose]);

  return (
    <AnimatePresence>
      {isOpen && (
        <motion.div
          ref={overlayRef}
          className="fixed inset-0 z-overlay flex items-center justify-center p-4"
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          transition={{ duration: 0.2 }}
          onClick={(e) => {
            if (e.target === overlayRef.current) onClose();
          }}
        >
          {/* Backdrop */}
          <div className="absolute inset-0 bg-ink/50 backdrop-blur-sm" />

          {/* Panel */}
          <motion.div
            className={cn(
              'relative z-modal bg-vellum-deep rounded-xl w-full shadow-gilt-lg border border-vellum-dark',
              maxWidth,
              className
            )}
            initial={{ opacity: 0, y: -8, scale: 0.98 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: -8, scale: 0.98 }}
            transition={{ duration: 0.25, ease: [0, 0, 0.2, 1] as [number, number, number, number] }}
          >
            {/* Header */}
            {title && (
              <div className="flex items-start justify-between p-6 pb-0">
                <div className="font-display text-display-md text-ink">{title}</div>
                <button
                  onClick={onClose}
                  className="p-1 rounded-md text-ink-muted hover:text-ink hover:bg-vellum-dark transition-colors"
                  aria-label={t('common.closeDialog')}
                >
                  <X className="w-5 h-5" />
                </button>
              </div>
            )}

            {/* Close button if no title */}
            {!title && (
              <button
                onClick={onClose}
                className="absolute top-4 right-4 p-1 rounded-md text-ink-muted hover:text-ink hover:bg-vellum-dark transition-colors"
                aria-label={t('common.closeDialog')}
              >
                <X className="w-5 h-5" />
              </button>
            )}

            {/* Content */}
            <div className="p-6">{children}</div>

            {/* Footer */}
            {footer && (
              <div className="flex justify-end gap-3 px-6 pb-6">{footer}</div>
            )}
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  );
}
