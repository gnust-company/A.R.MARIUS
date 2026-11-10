import { toast } from 'sonner'
import i18n from '@/i18n'
import { ApiError, errorText } from './errors'

/**
 * Say that a read the screen depends on did not come back.
 *
 * These reads used to end in an empty `catch`, so a dropped connection or a refusing server
 * left the screen showing whatever it had, with nothing to tell the person it was stale.
 * One toast id for all of them: a screen that asks for ten projects at once and loses the
 * network gets one notice, not ten.
 *
 * Two outcomes stay quiet on purpose. A 401 is the session ending, which has its own path
 * back to the login screen. A 404 is an answer, not a failure — the thing is gone, and the
 * screen that asked for it is the one to say so.
 */
export function notifyLoadFailed(e: unknown) {
  if (e instanceof ApiError && (e.status === 401 || e.status === 404)) return
  if (e instanceof DOMException && e.name === 'AbortError') return
  // A refusal with a code this build has a phrase for is worth showing as-is; anything else
  // (a network error reads "Failed to fetch") gets the plain advice.
  const known = e instanceof ApiError && e.code && i18n.exists(`errors.${e.code}`)
  toast.error(i18n.t('notify.loadFailedTitle'), {
    id: 'load-failed',
    description: known ? errorText(e, i18n.t) : i18n.t('notify.loadFailedBody'),
    action: { label: i18n.t('notify.reload'), onClick: () => window.location.reload() },
  })
}
