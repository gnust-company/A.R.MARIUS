// Authentication page (Sprint 6). Real JWT login/register against `/auth/*`.
// The `RequireAuth` wrapper redirects any unauthenticated visit to `/login`.

import { useState, type FormEvent } from 'react'
import { useTranslation } from 'react-i18next'
import { useNavigate } from 'react-router'
import { AlertCircle, ArrowRight, Loader2 } from 'lucide-react'

import { login, register } from '@/lib/auth'
import { errorText } from '@/lib/errors'
import { userToVM } from '@/lib/mappers';
import { useAppStore } from '@/store/appStore'
import { cn } from '@/lib/utils'
import EntryFrame from '@/components/EntryFrame'

const labelCls = 'block font-body text-body-sm font-medium text-ink mb-1.5'

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

  // The tagline is three short sentences; each gets its own line on a wide screen and the last
  // one carries the accent, the way the landing sets its headline. Split on sentence ends so
  // the same rule holds in every language.
  const tagline = t('app.tagline').split(/(?<=[.!?])\s+/)

  return (
    <EntryFrame center>
      <div className="w-full max-w-[1120px] grid gap-7 sm:gap-10 lg:grid-cols-[minmax(0,1fr)_440px] lg:gap-20 lg:items-center">
        <section className="min-w-0 max-w-[460px] mx-auto text-center lg:max-w-none lg:mx-0 lg:text-left">
          <p className="eyebrow">{t('login.heroEyebrow')}</p>
          <p className="mt-3 font-display font-normal leading-[1.08] tracking-[-0.035em] text-ink-strong text-[28px] sm:text-[36px] lg:text-[clamp(46px,4.6vw,66px)]">
            {tagline.map((line, i) => (
              <span
                key={i}
                className={cn('lg:block', i === tagline.length - 1 && tagline.length > 1 && 'text-sapphire-strong')}
              >
                {line}{i < tagline.length - 1 ? ' ' : ''}
              </span>
            ))}
          </p>
          <p className="hidden sm:block mt-4 lg:mt-6 max-w-[52ch] mx-auto lg:mx-0 font-body text-body-md lg:text-body-lg text-ink-light">
            {t('login.heroLead')}
          </p>
        </section>

        <div className="w-full max-w-[440px] mx-auto">
          <div className="surface shadow-gilt px-5 py-6 sm:px-8 sm:py-8">
            <p className="eyebrow">{registering ? t('login.registerEyebrow') : t('login.signInEyebrow')}</p>
            <h1 className="mt-2 font-display font-normal text-display-md text-ink-strong">
              {registering ? t('login.registerTitle') : t('login.signInTitle')}
            </h1>
            <p className="mt-1.5 font-body text-body-sm text-ink-light">
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
                    className="field"
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
                  className="field"
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
                  className="field"
                />
                {registering && (
                  <p className="mt-1.5 font-body text-body-sm text-ink-muted">{t('login.passwordHint')}</p>
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
                    className="field"
                  />
                </div>
              )}

              {error && (
                <p
                  className="flex items-start gap-2 rounded-md border border-danger/30 bg-danger-soft px-3 py-2 font-body text-body-sm text-danger"
                  role="alert"
                >
                  <AlertCircle className="w-4 h-4 mt-0.5 shrink-0" aria-hidden />
                  <span className="min-w-0">{error}</span>
                </p>
              )}

              <button type="submit" disabled={busy} className="btn btn-primary w-full !mt-6 disabled:cursor-wait">
                {busy && <Loader2 className="w-4 h-4 animate-spin" aria-hidden />}
                {busy
                  ? registering ? t('login.creating') : t('login.signingIn')
                  : registering ? t('login.createAccount') : t('login.signIn')}
                {!busy && <ArrowRight className="w-4 h-4" aria-hidden />}
              </button>
            </form>
          </div>

          <p className="mt-4 text-center font-body text-body-sm text-ink-light">
            {registering ? t('login.haveAccount') : t('login.noAccount')}{' '}
            <button type="button" onClick={switchMode} className="btn-text">
              {registering ? t('login.toLogin') : t('login.toRegister')}
            </button>
          </p>
        </div>
      </div>
    </EntryFrame>
  )
}
