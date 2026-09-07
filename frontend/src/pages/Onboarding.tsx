// The three steps a new account walks through before it is inside a workspace (FR-100).
//
// It exists because the alternative was silence: registering used to create a workspace called
// "Personal" without asking, and drop the person on a list with one row in it. Both questions
// here are things the system was already answering on somebody's behalf, which is the whole
// reason they are worth asking — this screen adds no field that nothing consumes.
//
// Deliberately outside `/w/:workspaceId`. The workspace exists by now (registering makes one),
// but naming it is one of the steps, so a layout with that workspace's sidebar around it would
// be showing the answer beside the question.

import { useCallback, useEffect, useState, type FormEvent } from 'react'
import { useTranslation } from 'react-i18next'
import { useNavigate } from 'react-router'
import { motion } from 'framer-motion'
import { ArrowRight, Check, Copy, Laptop, User as UserIcon } from 'lucide-react'

import { updateMe, updateWorkspace } from '@/lib/api'
import { errorText } from '@/lib/errors'
import { DOCS } from '@/lib/docs'
import { copyToClipboard, cn, wsHref } from '@/lib/utils'
import { useAppStore } from '@/store/appStore'
import VellumPanel from '@/components/VellumPanel'

/** The one command that installs the daemon, kept beside the docs that explain it. */
const INSTALL =
  'curl -fsSL https://raw.githubusercontent.com/gnust-company/A.R.MARIUS/main/scripts/install.sh | bash'

const STEPS = 3

/** A command a person is meant to run somewhere else, with a button that takes it with them.
 *
 *  Copy rather than *type this out*: the install line is 88 characters of URL, and a typo in it
 *  is a 404 the person has no way to read. */
function Command({ text }: { text: string }) {
  const { t } = useTranslation()
  const [copied, setCopied] = useState(false)

  async function take() {
    if (await copyToClipboard(text)) {
      setCopied(true)
      window.setTimeout(() => setCopied(false), 2000)
    }
  }

  return (
    <div className="flex items-start gap-2 rounded-md bg-vellum border border-vellum-dark p-3">
      <code className="flex-1 min-w-0 font-mono text-[12px] text-ink break-all">{text}</code>
      <button
        type="button"
        onClick={take}
        className="shrink-0 p-1.5 rounded-md text-ink-muted hover:text-ink hover:bg-vellum-dark transition-colors"
        aria-label={t('firstSteps.copy')}
      >
        {copied ? <Check className="w-4 h-4" aria-hidden /> : <Copy className="w-4 h-4" aria-hidden />}
      </button>
    </div>
  )
}

export default function Onboarding() {
  const { t } = useTranslation()
  const navigate = useNavigate()
  const currentUser = useAppStore((s) => s.currentUser)
  const setCurrentUser = useAppStore((s) => s.setCurrentUser)
  const workspaces = useAppStore((s) => s.workspaces)
  const hydrateWorkspaces = useAppStore((s) => s.hydrateWorkspaces)

  // Resumed from the server, not from this tab: leaving half way through and coming back on
  // another machine has to land on the step they stopped at (FR-104).
  const [step, setStep] = useState(() => Math.min(currentUser?.onboardingStep ?? 0, STEPS - 1))
  // `null` means *nobody has typed here yet*, so the box shows the name they signed up with —
  // including when that person arrives a render later, after a hard refresh on this page. Any
  // string, empty included, is something they typed and is left alone. Derived rather than
  // seeded by an effect: an effect that writes state on arrival is a second source for one
  // value, and the two disagree for exactly one frame.
  const [typedName, setTypedName] = useState<string | null>(null)
  const name = typedName ?? currentUser?.name ?? ''
  const [workspaceName, setWorkspaceName] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  const workspace = workspaces[0]

  useEffect(() => {
    void hydrateWorkspaces().catch(() => {})
  }, [hydrateWorkspaces])

  const finish = useCallback(async () => {
    setBusy(true)
    try {
      const saved = await updateMe({ onboarding_step: STEPS, onboarding_done: true })
      setCurrentUser({
        id: saved.id,
        name: saved.full_name,
        email: saved.email,
        onboardingStep: saved.onboarding_step ?? STEPS,
        onboarded: saved.onboarded ?? true,
      })
      navigate(workspace ? wsHref(workspace.id, '/projects') : '/workspaces')
    } catch (err) {
      setError(errorText(err, t))
      setBusy(false)
    }
  }, [navigate, setCurrentUser, t, workspace])

  async function saveName(e: FormEvent) {
    e.preventDefault()
    setError(null)
    setBusy(true)
    try {
      const saved = await updateMe({ full_name: name.trim(), onboarding_step: 1 })
      setCurrentUser({
        id: saved.id,
        name: saved.full_name,
        email: saved.email,
        onboardingStep: saved.onboarding_step ?? 1,
        onboarded: saved.onboarded ?? false,
      })
      setStep(1)
    } catch (err) {
      setError(errorText(err, t))
    }
    setBusy(false)
  }

  async function saveWorkspace(e: FormEvent) {
    e.preventDefault()
    setError(null)
    if (!workspace) {
      setError(t('firstSteps.noWorkspace'))
      return
    }
    setBusy(true)
    try {
      // Renamed, not created: registering already made one, so making a second here would leave
      // anybody who closed the tab midway with two (FR-102).
      await updateWorkspace(workspace.id, workspaceName.trim())
      await hydrateWorkspaces()
      await updateMe({ onboarding_step: 2 })
      setStep(2)
    } catch (err) {
      setError(errorText(err, t))
    }
    setBusy(false)
  }

  const inputCls = cn(
    'w-full px-3 py-2 rounded-md bg-vellum border border-vellum-dark',
    'font-body text-body-md text-ink placeholder:text-ink-muted',
    'focus:outline-none focus:border-terracotta focus:ring-[3px] focus:ring-terracotta/15 transition-all',
  )
  const buttonCls = cn(
    'w-full px-4 py-2 rounded-md font-body text-body-md transition-colors',
    'bg-terracotta text-white hover:bg-terracotta-light disabled:opacity-50',
  )
  const quietCls = 'font-body text-body-sm text-ink-muted hover:text-ink transition-colors'

  return (
    <div className="min-h-[100dvh] bg-vellum flex flex-col items-center justify-center px-6 py-12">
      <div
        className="fixed inset-0 pointer-events-none opacity-30"
        style={{ backgroundImage: 'url(/vellum-texture.jpg)', backgroundSize: '200px' }}
      />

      <motion.div
        className="w-full max-w-md relative z-10"
        initial={{ opacity: 0, y: 12 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.4 }}
      >
        <p className="font-body text-body-sm text-ink-muted text-center mb-2">
          {t('firstSteps.stepOf', { current: step + 1, total: STEPS })}
        </p>

        <VellumPanel hover={false}>
          {step === 0 && (
            <form onSubmit={saveName} className="space-y-5">
              <div className="flex items-start gap-3">
                <UserIcon className="w-5 h-5 mt-0.5 text-ink-light shrink-0" aria-hidden />
                <div className="min-w-0">
                  <h1 className="font-display text-display-sm text-ink">
                    {t('firstSteps.aboutYouTitle')}
                  </h1>
                  <p className="font-body text-body-sm text-ink-light">
                    {t('firstSteps.aboutYouLead')}
                  </p>
                </div>
              </div>

              <div>
                <label className="block font-body text-body-sm text-ink-light mb-1" htmlFor="ob-name">
                  {t('firstSteps.nameLabel')}
                </label>
                <input
                  id="ob-name"
                  value={name}
                  onChange={(e) => setTypedName(e.target.value)}
                  placeholder={t('firstSteps.namePlaceholder')}
                  autoFocus
                  className={inputCls}
                />
              </div>

              {error && (
                <p className="font-body text-body-sm text-terracotta" role="alert">
                  {error}
                </p>
              )}

              <button type="submit" disabled={busy || !name.trim()} className={buttonCls}>
                {t('firstSteps.next')}
              </button>
            </form>
          )}

          {step === 1 && (
            <form onSubmit={saveWorkspace} className="space-y-5">
              <div>
                <h1 className="font-display text-display-sm text-ink">
                  {t('firstSteps.workspaceTitle')}
                </h1>
                <p className="font-body text-body-sm text-ink-light">
                  {t('firstSteps.workspaceLead')}
                </p>
              </div>

              <div>
                <label className="block font-body text-body-sm text-ink-light mb-1" htmlFor="ob-workspace">
                  {t('firstSteps.workspaceLabel')}
                </label>
                <input
                  id="ob-workspace"
                  value={workspaceName}
                  onChange={(e) => setWorkspaceName(e.target.value)}
                  placeholder={t('firstSteps.workspacePlaceholder')}
                  autoFocus
                  className={inputCls}
                />
              </div>

              {error && (
                <p className="font-body text-body-sm text-terracotta" role="alert">
                  {error}
                </p>
              )}

              <button type="submit" disabled={busy || !workspaceName.trim()} className={buttonCls}>
                {t('firstSteps.next')}
              </button>
              <button type="button" onClick={() => setStep(0)} className={cn('w-full', quietCls)}>
                {t('firstSteps.back')}
              </button>
            </form>
          )}

          {step === 2 && (
            <div className="space-y-5">
              <div className="flex items-start gap-3">
                <Laptop className="w-5 h-5 mt-0.5 text-ink-light shrink-0" aria-hidden />
                <div className="min-w-0">
                  <h1 className="font-display text-display-sm text-ink">
                    {t('firstSteps.connectTitle')}
                  </h1>
                  <p className="font-body text-body-sm text-ink-light">
                    {t('firstSteps.connectLead')}
                  </p>
                </div>
              </div>

              <div className="space-y-2">
                <p className="font-body text-body-sm text-ink-light">
                  {t('firstSteps.installStep')}
                </p>
                <Command text={INSTALL} />
                <p className="font-body text-body-sm text-ink-light pt-1">
                  {t('firstSteps.loginStep')}
                </p>
                <Command text={`armarius-daemon login -server ${window.location.origin.replace(/:\d+$/, ':8080')}`} />
                <p className="font-body text-body-sm text-ink-muted">
                  {t('firstSteps.loginStepHint')}
                </p>
              </div>

              {error && (
                <p className="font-body text-body-sm text-terracotta" role="alert">
                  {error}
                </p>
              )}

              <button type="button" onClick={finish} disabled={busy} className={buttonCls}>
                {t('firstSteps.done')}
              </button>
              <div className="flex items-center justify-between">
                <button type="button" onClick={() => setStep(1)} className={quietCls}>
                  {t('firstSteps.back')}
                </button>
                <a
                  href={DOCS.machines}
                  target="_blank"
                  rel="noreferrer"
                  className={cn(quietCls, 'flex items-center gap-1')}
                >
                  {t('firstSteps.readGuide')}
                  <ArrowRight className="w-3.5 h-3.5" aria-hidden />
                </a>
              </div>
            </div>
          )}
        </VellumPanel>

        {/* Only on the last step. The two before it ask things the system would otherwise answer
            on somebody's behalf, which is the reason they exist; skipping them would put the
            silence back. Connecting a machine is different — it happens on another screen, on
            another machine, and the Machines page says how whenever they come back. */}
        {step === 2 && (
          <button type="button" onClick={finish} disabled={busy} className="mt-6 w-full text-center">
            <span className={quietCls}>{t('firstSteps.skip')}</span>
          </button>
        )}
      </motion.div>
    </div>
  )
}
