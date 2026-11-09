import { useState } from 'react';
import type { ReactNode } from 'react';
import { Loader2, AlertTriangle } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import Modal from './Modal';
import { cn } from '@/lib/utils';
import { errorText } from '@/lib/errors';

interface ConfirmDialogProps {
  isOpen: boolean;
  onClose: () => void;
  /** May be async. If it rejects, the dialog stays open and shows the error (e.g. a
   * backend constraint like "Built-in skills can't be deleted."). */
  onConfirm: () => void | Promise<void>;
  title: string;
  message: ReactNode;
  confirmLabel?: string;
  cancelLabel?: string;
  /** Danger-tinted confirm button for destructive actions (default true). */
  danger?: boolean;
}

export default function ConfirmDialog({
  isOpen,
  onClose,
  onConfirm,
  title,
  message,
  confirmLabel,
  cancelLabel,
  danger = true,
}: ConfirmDialogProps) {
  const { t } = useTranslation();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleConfirm = async () => {
    setBusy(true);
    setError(null);
    try {
      await onConfirm();
      setBusy(false);
      onClose();
    } catch (e) {
      setBusy(false);
      setError(errorText(e, t));
    }
  };

  const handleClose = () => {
    if (busy) return;
    setError(null);
    onClose();
  };

  return (
    <Modal
      isOpen={isOpen}
      onClose={handleClose}
      title={title}
      eyebrow={danger ? t('common.confirmEyebrow') : undefined}
      maxWidth="sm:max-w-md"
      footer={
        <>
          <button type="button" onClick={handleClose} disabled={busy} className="btn btn-secondary">
            {cancelLabel || t('common.cancel')}
          </button>
          <button
            type="button"
            onClick={handleConfirm}
            disabled={busy}
            className={cn('btn', danger ? 'btn-danger' : 'btn-primary')}
          >
            {busy && <Loader2 className="h-4 w-4 animate-spin" aria-hidden />}
            {confirmLabel || t('common.delete')}
          </button>
        </>
      }
    >
      <div className="space-y-3">
        <p className="font-body text-body-md leading-relaxed text-ink-light break-words">{message}</p>
        {error && (
          <div
            className="flex items-start gap-2 rounded-md border border-danger/30 bg-danger-soft px-3 py-2 font-body text-body-sm text-danger"
            role="alert"
          >
            <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" aria-hidden />
            <span className="min-w-0">{error}</span>
          </div>
        )}
      </div>
    </Modal>
  );
}
