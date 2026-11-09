// Authentication page (Sprint 6). Real JWT login/register against `/auth/*`.
// The `RequireAuth` wrapper redirects any unauthenticated visit to `/login`.

import { useState, type FormEvent } from 'react'
import { useTranslation } from 'react-i18next'
import { useNavigate } from 'react-router'
import { AlertCircle, Loader2 } from 'lucide-react'

import { login, register } from '@/lib/auth'
import { errorText } from '@/lib/errors'
import { userToVM } from '@/lib/mappers';
import { useAppStore } from '@/store/appStore'
import { cn } from '@/lib/utils'
import { Wordmark } from '@/components/EntryFrame'

const labelCls = 'block font-body text-body-sm font-medium text-ink-light mb-1.5'
const inputCls = cn(
  'w-full min-h-[44px] px-3 rounded-md bg-inset border border-line-strong',
  'font-body text-body-md text-ink placeholder:text-ink-muted',
  'focus:outline-none focus:bg-paper focus:border-terracotta focus:ring-[3px] focus:ring-terracotta/15 transition-colors',
)

export default function Login() {
  const { t } = useTranslation()
  const navigate = useNavigate()
  const setCurrentUser = useAppStore((s) => s.setCurrentUser)
  const hydrateWorkspaces = useAppStore((s) => s.hydrateWorkspaces)

  const [mode, setMode] = useState<'login' | 'register'>('login')
  const [email, setEmail] = useState('')
  const [fullName, setFullName] = useState('')
  const [password, setPassword] = useState('')
  const [confirmPassword, setConfirmPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  const registering = mode === 'register'

  async function submit(e: FormEvent) {
    e.preventDefault()
    setError(null)
    // Register: require the two password entries to match before hitting the API.
    if (mode === 'register' && password !== confirmPassword) {
      setError(t('login.mismatch'))
      return
    }
    setBusy(true)
    try {
      let user
      if (mode === 'login') {
        user = await login(email.trim(), password)
      } else {
        user = await register(email.trim(), fullName.trim(), password)
      }
      setCurrentUser(userToVM(user))
      await hydrateWorkspaces()
      // Somebody who has not been through the first steps goes to them — whether they just
      // registered or are coming back to a set they left half done (FR-100, FR-104). Everyone
      // else lands where they always did.
      navigate(user.onboarded === false ? '/onboarding' : '/workspaces')
    } catch (err) {
      setError(errorText(err, t))
    }
    setBusy(false)
  }

  function switchMode() {
    setMode(registering ? 'login' : 'register')
    setError(null)
    setConfirmPassword('')
  }

  return (
    <main className="min-h-[100dvh] bg-vellum flex flex-col items-center justify-center px-4 py-10 sm:py-16">
      <div className="w-full max-w-[420px]">
        <div className="text-center mb-7">
          <Wordmark size="lg" />
          <p className="mt-3 font-body text-body-md text-ink-light">{t('app.tagline')}</p>
        </div>

        <div className="bg-paper border border-line rounded-xl shadow-gilt px-5 py-6 sm:px-8 sm:py-8">
          <h1 className="font-display font-medium text-[22px] leading-tight text-ink">
            {registering ? t('login.registerTitle') : t('login.signInTitle')}
          </h1>
          <p className="mt-1 font-body text-body-sm text-ink-light">
            {registering ? t('login.registerLead') : t('login.signInLead')}
          </p>

          <form onSubmit={submit} className="mt-6 space-y-4">
            {registering && (
              <div>
                <label htmlFor="fullName" className={labelCls}>{t('login.fullName')}</label>
                <input
                  id="fullName"
                  value={fullName}
                  onChange={(e) => setFullName(e.target.value)}
                  autoComplete="name"
                  required
                  className={inputCls}
                />
              </div>
            )}
            <div>
              <label htmlFor="email" className={labelCls}>{t('login.email')}</label>
              <input
                id="email"
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                autoComplete="email"
                required
                className={inputCls}
              />
            </div>
            <div>
              <label htmlFor="password" className={labelCls}>{t('login.password')}</label>
              <input
                id="password"
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                autoComplete={registering ? 'new-password' : 'current-password'}
                required
                minLength={8}
                className={inputCls}
              />
              {registering && (
                <p className="mt-1 font-body text-body-sm text-ink-muted">{t('login.passwordHint')}</p>
              )}
            </div>
            {registering && (
              <div>
                <label htmlFor="confirmPassword" className={labelCls}>{t('login.confirmPassword')}</label>
                <input
                  id="confirmPassword"
                  type="password"
                  value={confirmPassword}
                  onChange={(e) => setConfirmPassword(e.target.value)}
                  autoComplete="new-password"
                  required
                  minLength={8}
                  className={inputCls}
                />
              </div>
            )}

            {error && (
              <p
                className="flex items-start gap-2 rounded-md border border-[#EDB8B0] bg-vermilion-bg px-3 py-2 font-body text-body-sm text-vermilion-ink"
                role="alert"
              >
                <AlertCircle className="w-4 h-4 mt-0.5 shrink-0" aria-hidden />
                <span className="min-w-0">{error}</span>
              </p>
            )}

            <button
              type="submit"
              disabled={busy}
              className={cn(
                'w-full min-h-[44px] inline-flex items-center justify-center gap-2 rounded-md px-4',
                'bg-ink text-paper font-body text-body-md font-medium hover:bg-ink/85 transition-colors',
                'disabled:cursor-wait',
              )}
            >
              {busy && <Loader2 className="w-4 h-4 animate-spin" aria-hidden />}
              {busy
                ? registering ? t('login.creating') : t('login.signingIn')
                : registering ? t('login.createAccount') : t('login.signIn')}
            </button>
          </form>
        </div>

        <p className="mt-5 text-center font-body text-body-md text-ink-light">
          {registering ? t('login.haveAccount') : t('login.noAccount')}{' '}
          <button
            type="button"
            onClick={switchMode}
            className="inline-flex items-center min-h-[44px] font-medium text-terracotta hover:text-terracotta-dark underline-offset-4 hover:underline transition-colors"
          >
            {registering ? t('login.toLogin') : t('login.toRegister')}
          </button>
        </p>
      </div>
    </main>
  )
}
