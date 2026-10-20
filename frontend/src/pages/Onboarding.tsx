// The four steps a new account walks through before it is inside a workspace (spec 003 FR-100).
//
// It exists because the alternative was silence: registering used to create a workspace called
// "Personal" without asking, and drop the person on a list with one row in it. Every question
// here is something the system was already answering on somebody's behalf, which is the whole
// reason it is worth asking — this screen adds no field that nothing consumes.
//
// The last two steps teach the way in, in order: connect a machine, then set up the workspace's
// host on it. They used to stop at approving the machine, which left people inside a workspace
// where every agent was offline, and the host on a runtime the system had picked by a rule that
// meant nothing to them (FR-106, FR-112).
//
// Deliberately outside `/w/:workspaceId`. The workspace exists by now (registering makes one),
// but naming it is one of the steps, so a layout with that workspace's sidebar around it would
// be showing the answer beside the question.

import { useCallback, useEffect, useState, type FormEvent, type ReactNode } from 'react'
import { useTranslation } from 'react-i18next'
import { useNavigate } from 'react-router'
import { motion } from 'framer-motion'
import { ArrowRight, Bot, Check, Copy, Laptop, Loader2, User as UserIcon } from 'lucide-react'

import { updateMe, updateWorkspace } from '@/lib/api'
import { MACHINE_LINKED, WORKPLACES_REPORTED, subscribeWorkspaceEvents } from '@/lib/sse'
import { ApiError, errorText } from '@/lib/errors'
import { DOCS } from '@/lib/docs'
import { connectProgress } from '@/lib/firstSteps'
import { userToVM } from '@/lib/mappers'
import { currentRuntimeChoice } from '@/lib/runtimeChoice'
import { copyToClipboard, cn, wsHref } from '@/lib/utils'
import { useRuntimeOffer } from '@/hooks/use-runtime-offer'
import { useAppStore } from '@/store/appStore'
import VellumPanel from '@/components/VellumPanel'
import RuntimePicker from '@/components/agent/RuntimePicker'
import SystemPromptBlock from '@/components/agent/SystemPromptBlock'

/** The one command that installs the daemon, kept beside the docs that explain it. */
const INSTALL =
  'curl -fsSL https://raw.githubusercontent.com/gnust-company/A.R.MARIUS/main/scripts/install.sh | bash'

const STEPS = 4
/** Where each step sits, by the index `onboarding_step` resumes at (FR-104). */
const CONNECT = 2
const FIRST_AGENT = 3

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

/** One part of connecting a machine: a number until the system knows it is done, then a tick.
 *  The part being waited on stands out; the ones after it are there to read ahead, not yet to
 *  do. */
function Part({
  n,
  title,
  done,
  current,
  children,
}: {
  n: number
  title: string
  done: boolean
  current: boolean
  children: ReactNode
}) {
  const { t } = useTranslation()
  return (
    <section className={cn('flex gap-3', !done && !current && 'opacity-60')}>
      <span
        className={cn(
          'flex h-6 w-6 shrink-0 items-center justify-center rounded-full border font-body text-body-sm',
          done
            ? 'border-terracotta bg-terracotta text-white'
            : current
              ? 'border-terracotta text-terracotta'
              : 'border-vellum-dark text-ink-muted',
        )}
        aria-hidden
      >
        {done ? <Check className="h-3.5 w-3.5" /> : n}
      </span>
      <div className="min-w-0 flex-1 space-y-2">
        <h2 className="font-body text-body-md text-ink">
          {title}
          {done && (
            <span className="ml-2 font-body text-body-sm text-ink-muted">{t('firstSteps.partDone')}</span>
          )}
        </h2>
        {children}
      </div>
    </section>
  )
}

export default function Onboarding() {
  const { t } = useTranslation()
  const navigate = useNavigate()
  const currentUser = useAppStore((s) => s.currentUser)
  const setCurrentUser = useAppStore((s) => s.setCurrentUser)
  const workspaces = useAppStore((s) => s.workspaces)
  const mariuses = useAppStore((s) => s.mariuses)
  const hydrateWorkspaces = useAppStore((s) => s.hydrateWorkspaces)
  const placeHost = useAppStore((s) => s.placeHost)

  // Resumed from the server, not from this tab: leaving half way through and coming back on
  // another machine has to land on the step they stopped at (FR-104). Somebody who stopped at
  // the old third step lands on connecting a machine, which is where the new flow has it.
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
  // Held apart from the object because it is what the effects below depend on: the store hands
  // back a fresh array on every hydrate, so depending on the workspace itself would tear down
  // and reopen the stream underneath for a value that never changed.
  const workspaceId = workspace?.id

  // ── Connecting a machine ──────────────────────────────────────────────────────────────
  const offer = useRuntimeOffer(workspaceId)
  const reloadOffer = offer.reload
  const [heardLinked, setHeardLinked] = useState(false)
  const progress = connectProgress(offer.machines, heardLinked)
  // The step moves on by itself once a machine has reported its runtimes (FR-121) — derived,
  // not set, so arriving here with a machine that already did lands on the next step at once.
  const shownStep = step === CONNECT && progress.running ? FIRST_AGENT : step

  // ── The first agent ───────────────────────────────────────────────────────────────────
  const host = mariuses.find((m) => m.id === workspace?.workspaceAgentId)
  const hostName = host?.displayName || host?.name || ''
  // Same rule as the name box above: the host's instructions until somebody types.
  const [typedInstructions, setTypedInstructions] = useState<string | null>(null)
  const instructions = typedInstructions ?? host?.instructions ?? ''
  const [picked, setPicked] = useState<string | null>(null)
  const chosen = currentRuntimeChoice(offer.ready, picked)
  // Placed by this window. A retry after the second half failed must not read its own success
  // back as somebody else's.
  const [placedHere, setPlacedHere] = useState(false)
  const [placedElsewhere, setPlacedElsewhere] = useState<{ cli: string; machine: string } | null>(
    null,
  )
  const placedAt =
    placedElsewhere ??
    (!placedHere && host?.runtime
      ? { cli: host.runtime.cli_kind, machine: host.runtime.machine_name }
      : null)

  useEffect(() => {
    void hydrateWorkspaces().catch(() => {})
  }, [hydrateWorkspaces])

  // The approval page is another window — the daemon opens it (FR-001b) — and starting the
  // daemon happens in a terminal. Neither can tell this window anything except through the
  // server, which announces both on the workspace channel: `machine.linked` when the machine is
  // approved, `machine.workplaces_reported` whenever it reports its runtimes, stopping included.
  // Each is a signal to read again, and nothing here asks in a loop (Constitution IV). One
  // stream for both steps, so moving from one to the other does not reconnect.
  const listening = shownStep >= CONNECT
  useEffect(() => {
    if (!listening || !workspaceId) return
    return subscribeWorkspaceEvents(workspaceId, (event) => {
      if (event.type === MACHINE_LINKED) {
        setHeardLinked(true)
        reloadOffer()
      } else if (event.type === WORKPLACES_REPORTED) {
        reloadOffer()
      }
    })
  }, [listening, workspaceId, reloadOffer])

  // Write down that connecting is done the moment the screen moves past it, so reloading lands
  // on the first agent rather than back on the commands.
  const savedStep = currentUser?.onboardingStep ?? 0
  useEffect(() => {
    if (shownStep !== FIRST_AGENT || savedStep >= FIRST_AGENT) return
    updateMe({ onboarding_step: FIRST_AGENT })
      .then((saved) => setCurrentUser(userToVM(saved)))
      .catch(() => {})
  }, [shownStep, savedStep, setCurrentUser])

  const markDone = useCallback(async () => {
    const saved = await updateMe({ onboarding_step: STEPS, onboarding_done: true })
    setCurrentUser(userToVM(saved))
  }, [setCurrentUser])

  async function skip() {
    setError(null)
    setBusy(true)
    try {
      await markDone()
      navigate(workspaceId ? wsHref(workspaceId, '/projects') : '/workspaces')
    } catch (err) {
      setError(errorText(err, t))
      setBusy(false)
    }
  }

  async function saveName(e: FormEvent) {
    e.preventDefault()
    setError(null)
    setBusy(true)
    try {
      const saved = await updateMe({ full_name: name.trim(), onboarding_step: 1 })
      setCurrentUser(userToVM(saved))
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
      const saved = await updateMe({ onboarding_step: CONNECT })
      setCurrentUser(userToVM(saved))
      setStep(CONNECT)
      // Read on arrival: a machine linked on an earlier, abandoned try is already done (FR-121).
      reloadOffer()
    } catch (err) {
      setError(errorText(err, t))
    }
    setBusy(false)
  }

  // Three writes in order (research R9): put the host on the runtime with its instructions in
  // one go, mark the first steps done, then open the host's page where the chat with it lives.
  // Safe to press twice or from two windows (FR-127): the later press is refused with
  // `agent_already_placed`, which carries where the host went, and goes on as done.
  async function finishWithHost(e: FormEvent) {
    e.preventDefault()
    if (!workspaceId || !host || !chosen) return
    setError(null)
    setBusy(true)
    let elsewhere: { cli: string; machine: string } | null = null
    if (!placedHere) {
      try {
        await placeHost(workspaceId, host.id, chosen, instructions)
        setPlacedHere(true)
      } catch (err) {
        if (err instanceof ApiError && err.code === 'agent_already_placed') {
          elsewhere = { cli: err.params?.cli_kind ?? '', machine: err.params?.machine_name ?? '' }
        } else {
          setError(errorText(err, t))
          // The runtime went down between reading the list and pressing: read it again, so
          // what is on screen is what the server just refused against.
          if (err instanceof ApiError && err.code === 'placement_not_ready') reloadOffer()
          setBusy(false)
          return
        }
      }
    }
    try {
      await markDone()
    } catch (err) {
      setError(errorText(err, t))
      setBusy(false)
      return
    }
    if (elsewhere) {
      setPlacedElsewhere(elsewhere)
      setBusy(false)
      return
    }
    navigate(wsHref(workspaceId, `/agents/${host.id}`))
  }

  async function goToHost() {
    if (!workspaceId || !host) return
    setError(null)
    setBusy(true)
    try {
      if (currentUser?.onboarded === false) await markDone()
      navigate(wsHref(workspaceId, `/agents/${host.id}`))
    } catch (err) {
      setError(errorText(err, t))
      setBusy(false)
    }
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
  const errorLine = error && (
    <p className="font-body text-body-sm text-terracotta" role="alert">
      {error}
    </p>
  )

  return (
    <div className="min-h-[100dvh] bg-vellum flex flex-col items-center justify-center px-6 py-12">
      <div
        className="fixed inset-0 pointer-events-none opacity-30"
        style={{ backgroundImage: 'url(/vellum-texture.jpg)', backgroundSize: '200px' }}
      />

      <motion.div
        className="w-full max-w-xl relative z-10"
        initial={{ opacity: 0, y: 12 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.4 }}
      >
        <p className="font-body text-body-sm text-ink-muted text-center mb-2">
          {t('firstSteps.stepOf', { current: shownStep + 1, total: STEPS })}
        </p>

        <VellumPanel hover={false}>
          {shownStep === 0 && (
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

              {errorLine}

              <button type="submit" disabled={busy || !name.trim()} className={buttonCls}>
                {t('firstSteps.next')}
              </button>
            </form>
          )}

          {shownStep === 1 && (
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

              {errorLine}

              <button type="submit" disabled={busy || !workspaceName.trim()} className={buttonCls}>
                {t('firstSteps.next')}
              </button>
              <button type="button" onClick={() => setStep(0)} className={cn('w-full', quietCls)}>
                {t('firstSteps.back')}
              </button>
            </form>
          )}

          {shownStep === CONNECT && (
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

              {/* Installing has no mark of its own: the system cannot see it, and a linked
                  machine is proof enough that it happened (FR-120). */}
              <Part n={1} title={t('firstSteps.partInstall')} done={progress.linked} current={!progress.linked}>
                <p className="font-body text-body-sm text-ink-light">{t('firstSteps.installStep')}</p>
                <Command text={INSTALL} />
              </Part>

              <Part n={2} title={t('firstSteps.partLink')} done={progress.linked} current={!progress.linked}>
                <p className="font-body text-body-sm text-ink-light">{t('firstSteps.loginStep')}</p>
                {/* The address this page is being read at, exactly as it is. It used to rewrite
                    the port to `:8080`, which is true of one developer's compose file and of
                    nowhere else: a deployment on a real address serves the API from the same
                    origin as the SPA (nginx proxies `/daemon` beside it), and `:8080` there is
                    usually not published at all. Whatever address a person reached this page
                    at is reachable — they are looking at it (FR-001c). */}
                <Command text={`armarius-daemon login -server ${window.location.origin}`} />
                <p className="font-body text-body-sm text-ink-muted">{t('firstSteps.loginStepHint')}</p>
                {!progress.linked && (
                  <p className="flex items-center gap-1.5 font-body text-body-sm text-ink-light" role="status">
                    <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden />
                    {t('firstSteps.waitingLink')}
                  </p>
                )}
              </Part>

              <Part n={3} title={t('firstSteps.partStart')} done={progress.running} current={progress.linked && !progress.running}>
                <p className="font-body text-body-sm text-ink-light">{t('firstSteps.startStep')}</p>
                <Command text="armarius-daemon start" />
                <p className="font-body text-body-sm text-ink-muted">{t('firstSteps.startStepHint')}</p>
                {progress.linked && !progress.running && (
                  <p className="flex items-center gap-1.5 font-body text-body-sm text-ink-light" role="status">
                    <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden />
                    {t('firstSteps.waitingStart')}
                  </p>
                )}
              </Part>

              {errorLine}

              <div className="flex items-center justify-between gap-3">
                <button type="button" onClick={() => setStep(1)} className={quietCls}>
                  {t('firstSteps.back')}
                </button>
                {/* A read on demand, for the one case the push cannot reach: the channel
                    dropped while the person was in the terminal. Not a loop. */}
                <button type="button" onClick={reloadOffer} className={quietCls}>
                  {t('firstSteps.checkAgain')}
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

          {shownStep === FIRST_AGENT && (
            <form onSubmit={finishWithHost} className="space-y-5">
              <div className="flex items-start gap-3">
                <Bot className="w-5 h-5 mt-0.5 text-ink-light shrink-0" aria-hidden />
                <div className="min-w-0">
                  <h1 className="font-display text-display-sm text-ink">{t('firstSteps.agentTitle')}</h1>
                  <p className="font-body text-body-sm text-ink-light">{t('firstSteps.agentLead')}</p>
                </div>
              </div>

              {!host ? (
                <p className="font-body text-body-sm text-ink-light">{t('firstSteps.agentNoHost')}</p>
              ) : placedAt ? (
                <div className="space-y-4">
                  <p className="font-body text-body-sm text-ink" role="status">
                    {t('firstSteps.agentAlreadyPlaced', {
                      name: hostName,
                      cli: placedAt.cli,
                      machine: placedAt.machine,
                    })}
                  </p>
                  {errorLine}
                  <button type="button" onClick={goToHost} disabled={busy} className={buttonCls}>
                    {t('firstSteps.agentGoToHost', { name: hostName })}
                  </button>
                </div>
              ) : (
                <>
                  <div>
                    <p className="font-body text-body-sm text-ink-light mb-1">{t('firstSteps.agentNameLabel')}</p>
                    <p className="font-body text-body-md text-ink">{hostName}</p>
                  </div>

                  {(host.systemInstructions ?? '').trim() && (
                    <SystemPromptBlock text={host.systemInstructions ?? ''} defaultOpen />
                  )}

                  <div>
                    <label
                      className="block font-body text-body-sm text-ink-light mb-1"
                      htmlFor="ob-instructions"
                    >
                      {t('firstSteps.agentInstructionsLabel')}
                    </label>
                    <p className="mb-2 font-body text-body-sm text-ink-muted">
                      {t('firstSteps.agentInstructionsHint')}
                    </p>
                    <textarea
                      id="ob-instructions"
                      value={instructions}
                      onChange={(e) => setTypedInstructions(e.target.value)}
                      rows={6}
                      className={cn(inputCls, 'font-mono text-[12px] leading-relaxed')}
                    />
                  </div>

                  <div>
                    <p className="font-body text-body-sm text-ink-light mb-2">{t('firstSteps.agentRuntimeLabel')}</p>
                    <RuntimePicker
                      ready={offer.ready}
                      machines={offer.machines}
                      chosen={chosen}
                      onChoose={setPicked}
                      loading={offer.loading}
                      disabled={busy}
                    />
                  </div>

                  {errorLine}

                  <button type="submit" disabled={busy || !chosen} className={buttonCls}>
                    {t('firstSteps.agentFinish', { name: hostName })}
                  </button>
                  <div className="flex justify-end">
                    <a
                      href={DOCS.agents}
                      target="_blank"
                      rel="noreferrer"
                      className={cn(quietCls, 'flex items-center gap-1')}
                    >
                      {t('firstSteps.readGuide')}
                      <ArrowRight className="w-3.5 h-3.5" aria-hidden />
                    </a>
                  </div>
                </>
              )}
            </form>
          )}
        </VellumPanel>

        {/* Only on the last two steps. The two before them ask things the system would otherwise
            answer on somebody's behalf, which is the reason they exist; skipping them would put
            the silence back. A machine and a runtime are different — they happen elsewhere, and
            the Machines page and the host's own page say how whenever they come back (FR-128). */}
        {shownStep === CONNECT && (
          <button type="button" onClick={skip} disabled={busy} className="mt-6 w-full text-center">
            <span className={quietCls}>{t('firstSteps.skip')}</span>
          </button>
        )}
        {shownStep === FIRST_AGENT && host && !placedAt && (
          <button type="button" onClick={skip} disabled={busy} className="mt-6 w-full text-center">
            <span className={quietCls}>{t('firstSteps.agentSkip', { name: hostName })}</span>
          </button>
        )}
        {shownStep === FIRST_AGENT && !host && (
          <button type="button" onClick={skip} disabled={busy} className="mt-6 w-full text-center">
            <span className={quietCls}>{t('firstSteps.skip')}</span>
          </button>
        )}
      </motion.div>
    </div>
  )
}
