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
import { useLocation, useNavigate } from 'react-router'
import { motion } from 'framer-motion'
import {
  AlertCircle,
  ArrowLeft,
  ArrowUpRight,
  Bot,
  Building2,
  Check,
  Copy,
  Laptop,
  Loader2,
  RotateCw,
  TerminalSquare,
  User as UserIcon,
} from 'lucide-react'

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
import EntryFrame from '@/components/EntryFrame'
import RuntimePicker from '@/components/agent/RuntimePicker'
import SystemPromptBlock from '@/components/agent/SystemPromptBlock'
import { notifyLoadFailed } from '@/lib/notify'

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
    <div className="flex items-stretch min-h-[44px] rounded-md bg-canvas-deep border border-line overflow-hidden">
      <TerminalSquare className="hidden sm:block shrink-0 self-center ml-3 w-4 h-4 text-ink-muted" aria-hidden />
      <code className="flex-1 min-w-0 self-center px-3 sm:px-2.5 py-2 font-mono text-mono-sm text-sapphire-strong break-all">{text}</code>
      <button
        type="button"
        onClick={take}
        className={cn(
          'shrink-0 w-11 flex items-center justify-center border-l border-line transition-colors',
          copied ? 'text-success' : 'text-ink-muted hover:text-ink-strong hover:bg-surface-hover',
        )}
        aria-label={t('firstSteps.copy')}
        title={t('firstSteps.copy')}
      >
        {copied ? <Check className="w-4 h-4" aria-hidden /> : <Copy className="w-4 h-4" aria-hidden />}
      </button>
    </div>
  )
}

/** One part of connecting a machine: a number until the system knows it is done, then a tick.
 *  The part being waited on stands out; the ones after it are there to read ahead, not yet to
 *  do — their marker and title go quiet, the commands stay readable. */
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
    <section className="flex gap-3">
      <span
        className={cn(
          'flex h-8 w-8 shrink-0 items-center justify-center rounded-full border font-display text-[15px]',
          done
            ? 'border-success/40 bg-success-soft text-success'
            : current
              ? 'border-gold/60 bg-surface text-gold ring-4 ring-gold/10'
              : 'border-line bg-surface text-ink-faint',
        )}
        aria-hidden
      >
        {done ? <Check className="h-4 w-4" /> : n}
      </span>
      <div className="min-w-0 flex-1 space-y-2.5 pt-0.5">
        <h2
          className={cn(
            'flex flex-wrap items-center gap-x-2.5 gap-y-1 font-display font-normal text-[19px] leading-snug tracking-[-0.01em]',
            done || current ? 'text-ink-strong' : 'text-ink-light',
          )}
        >
          {title}
          {done && (
            <span className="status-pill border-success/40 text-success">
              <span className="status-dot bg-success" aria-hidden />
              {t('firstSteps.partDone')}
            </span>
          )}
        </h2>
        {children}
      </div>
    </section>
  )
}

/** The four steps as a row of numbered marks with their names, so a person can see how far
 *  they have come and what is left. On a phone the names would not fit four abreast, so only
 *  the current one is spelled out, under the row. */
function StepTrail({ current, labels }: { current: number; labels: string[] }) {
  const { t } = useTranslation()
  return (
    <nav aria-label={t('firstSteps.stepsLabel')} className="w-full">
      <ol className="flex items-start">
        {labels.map((label, i) => {
          const done = i < current
          const here = i === current
          return (
            <li
              key={label}
              className="relative flex-1 flex flex-col items-center gap-2 min-w-0"
              aria-current={here ? 'step' : undefined}
            >
              {/* The rule leading into this step from the one before it, drawn behind the mark. */}
              {i > 0 && (
                <span
                  className={cn(
                    'absolute top-4 right-1/2 w-full h-0.5 -translate-y-1/2',
                    i <= current ? 'bg-sapphire-strong' : 'bg-line',
                  )}
                  aria-hidden
                />
              )}
              <span
                className={cn(
                  'relative z-[1] flex h-8 w-8 items-center justify-center rounded-full border font-display text-[15px]',
                  done
                    ? 'border-sapphire-strong bg-sapphire-strong text-sapphire-ink'
                    : here
                      ? 'border-gold bg-surface text-gold ring-4 ring-gold/15'
                      : 'border-line-strong bg-canvas text-ink-faint',
                )}
              >
                {done ? <Check className="h-4 w-4" aria-hidden /> : i + 1}
              </span>
              <span
                className={cn(
                  'hidden sm:block px-1 text-center font-body text-body-sm leading-snug',
                  here ? 'text-ink-strong font-medium' : done ? 'text-ink-light' : 'text-ink-muted',
                )}
              >
                {label}
              </span>
              <span className="sr-only sm:hidden">{label}</span>
            </li>
          )
        })}
      </ol>
      <p className="sm:hidden mt-3 text-center font-body text-body-sm text-ink-light">
        {t('firstSteps.stepOf', { current: current + 1, total: labels.length })}
        {' · '}
        <span className="font-medium text-ink-strong">{labels[current]}</span>
      </p>
    </nav>
  )
}

export default function Onboarding() {
  const { t } = useTranslation()
  const navigate = useNavigate()
  const location = useLocation()
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
  // Heard on the channel, or carried here by the approval page itself when the person came back
  // from it: either way a machine was approved, whether or not its row exists yet.
  const [heardLinked, setHeardLinked] = useState(
    () => (location.state as { machineApproved?: boolean } | null)?.machineApproved === true,
  )
  const progress = connectProgress(offer.machines, heardLinked)
  // The step moves on by itself once a machine has reported its runtimes (FR-121) — derived,
  // not set, so arriving here with a machine that already did lands on the next step at once.
  const shownStep = step === CONNECT && progress.running ? FIRST_AGENT : step

  // ── The first agent ───────────────────────────────────────────────────────────────────
  const host = mariuses.find((m) => m.id === workspace?.workspaceAgentId)
  const hostName = host?.displayName || host?.name || ''
  // Same rule as the name box above, for the host's name and its instructions: what it has
  // until somebody types. Its name is the owner's to change here too (FR-122, revised
  // 2026-10-26) — the agent page already let them, so locking it on this step only sent them
  // the long way round.
  const [typedHostName, setTypedHostName] = useState<string | null>(null)
  const hostNameDraft = typedHostName ?? hostName
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
    void hydrateWorkspaces().catch(notifyLoadFailed)
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
      navigate(workspaceId ? wsHref(workspaceId, '/home') : '/workspaces')
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
    if (!workspaceId || !host || !chosen || !hostNameDraft.trim()) return
    setError(null)
    setBusy(true)
    let elsewhere: { cli: string; machine: string } | null = null
    if (!placedHere) {
      try {
        await placeHost(workspaceId, host.id, chosen, {
          instructions,
          name: hostNameDraft.trim(),
        })
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

  const inputCls = 'field'
  const labelCls = 'block font-body text-body-sm font-medium text-ink mb-1.5'
  const buttonCls = 'btn btn-primary whitespace-normal text-center'
  const ghostCls = 'btn btn-ghost font-medium whitespace-normal text-center'
  const linkCls = 'btn-text'
  // Back on the left, the way on at the right; on a phone the way on comes first, full width.
  const footerCls = 'flex flex-col-reverse sm:flex-row sm:items-center sm:justify-between gap-2 pt-2'
  const errorLine = error && (
    <p
      className="flex items-start gap-2 rounded-md border border-danger/30 bg-danger-soft px-3 py-2 font-body text-body-sm text-danger"
      role="alert"
    >
      <AlertCircle className="w-4 h-4 mt-0.5 shrink-0" aria-hidden />
      <span className="min-w-0">{error}</span>
    </p>
  )
  const heading = (icon: ReactNode, title: string, lead: string) => (
    <div className="flex items-start gap-4">
      <span className="hidden sm:flex w-12 h-12 shrink-0 rounded-full border border-line-strong items-center justify-center text-sapphire-strong">
        {icon}
      </span>
      <div className="min-w-0">
        {/* The phone's step trail already spells this out right above the card. */}
        <p className="eyebrow hidden sm:block mb-1.5">{t('firstSteps.stepOf', { current: shownStep + 1, total: STEPS })}</p>
        <h1 className="font-display font-normal text-[26px] sm:text-display-md text-ink-strong">{title}</h1>
        <p className="mt-2 font-body text-body-md text-ink-light">{lead}</p>
      </div>
    </div>
  )

  return (
    <EntryFrame>
      <motion.div
        className="w-full max-w-[720px]"
        initial={{ opacity: 0, y: 8 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.2 }}
      >
        <div className="mb-6 sm:mb-9">
          <p className="eyebrow text-center mb-4 sm:mb-5">{t('firstSteps.eyebrow')}</p>
          <StepTrail
            current={shownStep}
            labels={[
              t('firstSteps.stepAboutYou'),
              t('firstSteps.stepWorkspace'),
              t('firstSteps.stepMachine'),
              t('firstSteps.stepAgent'),
            ]}
          />
        </div>

        <div className="surface shadow-gilt px-5 py-6 sm:p-9">
          {shownStep === 0 && (
            <form onSubmit={saveName} className="space-y-6">
              {heading(
                <UserIcon className="w-5 h-5" aria-hidden />,
                t('firstSteps.aboutYouTitle'),
                t('firstSteps.aboutYouLead'),
              )}

              <div>
                <label className={labelCls} htmlFor="ob-name">
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

              <div className={cn(footerCls, 'sm:justify-end')}>
                <button type="submit" disabled={busy || !name.trim()} className={buttonCls}>
                  {t('firstSteps.next')}
                </button>
              </div>
            </form>
          )}

          {shownStep === 1 && (
            <form onSubmit={saveWorkspace} className="space-y-6">
              {heading(
                <Building2 className="w-5 h-5" aria-hidden />,
                t('firstSteps.workspaceTitle'),
                t('firstSteps.workspaceLead'),
              )}

              <div>
                <label className={labelCls} htmlFor="ob-workspace">
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

              <div className={footerCls}>
                <button type="button" onClick={() => setStep(0)} className={ghostCls}>
                  <ArrowLeft className="w-4 h-4" aria-hidden />
                  {t('firstSteps.back')}
                </button>
                <button type="submit" disabled={busy || !workspaceName.trim()} className={buttonCls}>
                  {t('firstSteps.next')}
                </button>
              </div>
            </form>
          )}

          {shownStep === CONNECT && (
            <div className="space-y-6">
              {heading(
                <Laptop className="w-5 h-5" aria-hidden />,
                t('firstSteps.connectTitle'),
                t('firstSteps.connectLead'),
              )}

              {/* Installing has no mark of its own: the system cannot see it, and a linked
                  machine is proof enough that it happened (FR-120). */}
              <Part n={1} title={t('firstSteps.partInstall')} done={progress.linked} current={!progress.linked}>
                <p className="font-body text-body-md text-ink-light">{t('firstSteps.installStep')}</p>
                <Command text={INSTALL} />
              </Part>

              <Part n={2} title={t('firstSteps.partLink')} done={progress.linked} current={!progress.linked}>
                <p className="font-body text-body-md text-ink-light">{t('firstSteps.loginStep')}</p>
                {/* The address this page is being read at, exactly as it is. It used to rewrite
                    the port to `:8080`, which is true of one developer's compose file and of
                    nowhere else: a deployment on a real address serves the API from the same
                    origin as the SPA (nginx proxies `/daemon` beside it), and `:8080` there is
                    usually not published at all. Whatever address a person reached this page
                    at is reachable — they are looking at it (FR-001c). */}
                <Command text={`armarius-daemon login -server ${window.location.origin}`} />
                <p className="font-body text-body-sm text-ink-muted">{t('firstSteps.loginStepHint')}</p>
                {!progress.linked && (
                  <p
                    className="flex items-center gap-2.5 rounded-md border border-dashed border-gold/50 bg-gold-soft/60 px-3 py-2.5 font-body text-body-sm text-ink"
                    role="status"
                  >
                    <Loader2 className="h-4 w-4 shrink-0 animate-spin text-gold" aria-hidden />
                    {t('firstSteps.waitingLink')}
                  </p>
                )}
              </Part>

              <Part n={3} title={t('firstSteps.partStart')} done={progress.running} current={progress.linked && !progress.running}>
                <p className="font-body text-body-md text-ink-light">{t('firstSteps.startStep')}</p>
                <Command text="armarius-daemon start" />
                <p className="font-body text-body-sm text-ink-muted">{t('firstSteps.startStepHint')}</p>
                {progress.linked && !progress.running && (
                  <p
                    className="flex items-center gap-2.5 rounded-md border border-dashed border-sapphire/50 bg-sapphire-soft/60 px-3 py-2.5 font-body text-body-sm text-ink"
                    role="status"
                  >
                    <Loader2 className="h-4 w-4 shrink-0 animate-spin text-sapphire-strong" aria-hidden />
                    {t('firstSteps.waitingStart')}
                  </p>
                )}
              </Part>

              {errorLine}

              <div className="flex flex-wrap items-center justify-between gap-x-3 gap-y-1 border-t border-line pt-4">
                <button type="button" onClick={() => setStep(1)} className={cn(ghostCls, '-ml-3')}>
                  <ArrowLeft className="w-4 h-4" aria-hidden />
                  {t('firstSteps.back')}
                </button>
                <div className="flex flex-wrap items-center gap-x-4 gap-y-1">
                  {/* A read on demand, for the one case the push cannot reach: the channel
                      dropped while the person was in the terminal. Not a loop. */}
                  <button type="button" onClick={reloadOffer} className={ghostCls}>
                    <RotateCw className="w-4 h-4" aria-hidden />
                    {t('firstSteps.checkAgain')}
                  </button>
                  <a href={DOCS.machines} target="_blank" rel="noreferrer" className={linkCls}>
                    {t('firstSteps.readGuide')}
                    <ArrowUpRight className="w-4 h-4" aria-hidden />
                  </a>
                </div>
              </div>
            </div>
          )}

          {shownStep === FIRST_AGENT && (
            <form onSubmit={finishWithHost} className="space-y-6">
              {heading(
                <Bot className="w-5 h-5" aria-hidden />,
                t('firstSteps.agentTitle'),
                t('firstSteps.agentLead'),
              )}

              {!host ? (
                <p className="font-body text-body-md text-ink-light">{t('firstSteps.agentNoHost')}</p>
              ) : placedAt ? (
                <div className="space-y-4">
                  <p
                    className="flex items-start gap-2 rounded-md border border-success/30 bg-success-soft px-3 py-2.5 font-body text-body-md text-ink-strong"
                    role="status"
                  >
                    <Check className="w-4 h-4 mt-1 shrink-0 text-success" aria-hidden />
                    <span className="min-w-0">
                      {t('firstSteps.agentAlreadyPlaced', {
                        name: hostName,
                        cli: placedAt.cli,
                        machine: placedAt.machine,
                      })}
                    </span>
                  </p>
                  {errorLine}
                  <button type="button" onClick={goToHost} disabled={busy} className={cn(buttonCls, 'w-full')}>
                    {t('firstSteps.agentGoToHost', { name: hostName })}
                  </button>
                </div>
              ) : (
                <>
                  <div>
                    <label className={labelCls} htmlFor="ob-host-name">
                      {t('firstSteps.agentNameLabel')}
                    </label>
                    <input
                      id="ob-host-name"
                      value={hostNameDraft}
                      onChange={(e) => setTypedHostName(e.target.value)}
                      maxLength={200}
                      className={inputCls}
                    />
                  </div>

                  {(host.systemInstructions ?? '').trim() && (
                    <SystemPromptBlock text={host.systemInstructions ?? ''} defaultOpen />
                  )}

                  <div>
                    <label className={labelCls} htmlFor="ob-instructions">
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
                      className={cn(inputCls, 'py-2.5 font-mono text-mono-md leading-relaxed')}
                    />
                  </div>

                  <div>
                    <p className={labelCls}>{t('firstSteps.agentRuntimeLabel')}</p>
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

                  <div className={cn(footerCls, 'border-t border-line pt-4')}>
                    <a href={DOCS.agents} target="_blank" rel="noreferrer" className={cn(linkCls, 'justify-center')}>
                      {t('firstSteps.readGuide')}
                      <ArrowUpRight className="w-4 h-4" aria-hidden />
                    </a>
                    <button
                      type="submit"
                      disabled={busy || !chosen || !hostNameDraft.trim()}
                      className={buttonCls}
                    >
                      {t('firstSteps.agentFinish', { name: hostNameDraft.trim() || hostName })}
                    </button>
                  </div>
                </>
              )}
            </form>
          )}
        </div>

        {/* Only on the last two steps. The two before them ask things the system would otherwise
            answer on somebody's behalf, which is the reason they exist; skipping them would put
            the silence back. A machine and a runtime are different — they happen elsewhere, and
            the Machines page and the host's own page say how whenever they come back (FR-128). */}
        {shownStep === CONNECT && (
          <button type="button" onClick={skip} disabled={busy} className={cn(ghostCls, 'mt-4 w-full')}>
            {t('firstSteps.skip')}
          </button>
        )}
        {shownStep === FIRST_AGENT && host && !placedAt && (
          <button type="button" onClick={skip} disabled={busy} className={cn(ghostCls, 'mt-4 w-full')}>
            {t('firstSteps.agentSkip', { name: hostName })}
          </button>
        )}
        {shownStep === FIRST_AGENT && !host && (
          <button type="button" onClick={skip} disabled={busy} className={cn(ghostCls, 'mt-4 w-full')}>
            {t('firstSteps.skip')}
          </button>
        )}
      </motion.div>
    </EntryFrame>
  )
}
