// The approval screen for a machine asking to join a workspace (T031, FR-001).
//
// This is the human half of the device flow the daemon runs: someone types
// `armarius-daemon login` on their own box and says yes here. Deliberately a page of its own
// rather than something inside a workspace — at the moment the code arrives the machine
// belongs to no workspace yet, and choosing which one it joins is the decision being made
// here.
//
// The daemon opens this page with the code already on the address, so the usual arrival is
// straight at the confirmation step with nothing typed (FR-001a). Typing is still here, and
// still works, for the machine that had no browser to open.
//
// What arriving by link does *not* remove is the asking. A code on an address is a
// convenience; approval is the thing that stops a stranger's daemon from being let in, and a
// code that leaks — a screenshot, a log, a message — must still meet a person who looks at
// the hostname and does not recognise it.
//
// It is also the only door: nothing anywhere lets a machine admit itself.

import { useCallback, useEffect, useRef, useState, type FormEvent } from 'react'
import { useTranslation } from 'react-i18next'
import { useNavigate, useSearchParams } from 'react-router'
import { motion } from 'framer-motion'
import { ArrowLeft, Check, Laptop, Link2, Loader2, ShieldQuestion, TriangleAlert } from 'lucide-react'

import { approveMachineLink, getMachineLink, type PendingMachineLinkDTO } from '@/lib/api'
import { errorText } from '@/lib/errors'
import { useAppStore } from '@/store/appStore'
import EntryFrame, { WithCommands } from '@/components/EntryFrame'
import Dropdown from '@/components/Dropdown'
import { cn, wsHref } from '@/lib/utils'
import { notifyLoadFailed } from '@/lib/notify'

/** The alphabet the server draws codes from: no 0/O and no 1/I, because a person copies
 *  this off one screen and onto another. Anything else typed is punctuation to ignore. */
const CODE_CHARS = /[ABCDEFGHJKLMNPQRSTUVWXYZ23456789]/g
const CODE_LENGTH = 8

/** Format as the server prints it — `KQ7F-M2XD` — whatever the person actually typed.
 *  The dash is a reading aid this end added, so it must not be something they can get
 *  wrong; the server normalises the same way. */
function formatCode(typed: string): string {
  const kept = (typed.toUpperCase().match(CODE_CHARS) ?? []).join('').slice(0, CODE_LENGTH)
  return kept.length > 4 ? `${kept.slice(0, 4)}-${kept.slice(4)}` : kept
}

function isComplete(code: string): boolean {
  return (code.match(CODE_CHARS) ?? []).length === CODE_LENGTH
}

/** Roughly how many minutes the code has left, read once — deliberately not a live clock.
 *
 *  A ticking countdown would mean a timer on a screen, and this app does not put timers on
 *  screens (FR-080). It would also be decoration: a code that runs out while someone reads
 *  it is already handled by the only thing that can be right about it, which is the
 *  server's own refusal when they press approve. So the number is approximate and says so.
 */
function minutesLeft(expiresAt: string | null): number | null {
  if (!expiresAt) return null
  const remaining = Math.ceil((Date.parse(expiresAt) - Date.now()) / 60_000)
  return Number.isFinite(remaining) && remaining > 0 ? remaining : null
}

export default function LinkMachine() {
  const { t } = useTranslation()
  const navigate = useNavigate()
  const [params] = useSearchParams()
  const workspaces = useAppStore((s) => s.workspaces)
  const activeWorkspaceId = useAppStore((s) => s.activeWorkspaceId)
  const hydrateWorkspaces = useAppStore((s) => s.hydrateWorkspaces)
  const currentUser = useAppStore((s) => s.currentUser)

  const [code, setCode] = useState('')
  const [pending, setPending] = useState<PendingMachineLinkDTO | null>(null)
  // What the person picked in the box — empty until they touch it.
  const [chosenWorkspaceId, setChosenWorkspaceId] = useState('')
  const [approved, setApproved] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  // The code came off the address rather than out of somebody's fingers, which changes one
  // thing on this screen: what the warning has to say. A person who typed the code was
  // reading it off their own terminal a moment ago; a person who followed a link has no such
  // evidence and needs telling so.
  const [fromLink, setFromLink] = useState(false)
  // Whoever is here is still part way through their first steps. Approving no longer finishes
  // them (spec 003 FR-106), so this is the same before and after the button, and every way off
  // this page leads back to them rather than into a workspace they have not finished setting up.
  const inFirstSteps = currentUser?.onboarded === false

  useEffect(() => {
    void hydrateWorkspaces().catch(notifyLoadFailed)
  }, [hydrateWorkspaces])

  const remaining = pending ? minutesLeft(pending.expires_at) : null

  // Where leaving this page leads. `/link` sits outside every workspace on purpose, but the
  // person walked here from inside one and a way out that drops them at the workspace picker
  // makes them find their way back in by hand. Once a machine has been admitted the answer is
  // better still: the workspace it just joined, on the screen it now appears on.
  //
  // Deliberately not `navigate(-1)`. The daemon prints this page's address, so arriving here
  // with no history at all is a normal way to arrive, and going back one step from that
  // leaves the application.
  // The workspace to approve into: what they picked, else the one they came from, else the
  // first they own. **Derived, not seeded by an effect.** This cannot be settled inside the
  // lookup either — on a cold load the list is still arriving while the code is being looked
  // up, and a machine found before the list lands would leave the approve button disabled with
  // a workspace visibly selected in the box beside it. An effect that wrote it once solved
  // that and brought back the fault ESLint names: state written from an effect body is a
  // second source for one value, and for a frame the two disagree.
  const workspaceId =
    chosenWorkspaceId || (pending ? (activeWorkspaceId ?? workspaces[0]?.id ?? '') : '')

  const leaveTo = inFirstSteps
    ? '/onboarding'
    : activeWorkspaceId
      ? wsHref(activeWorkspaceId, '/machines')
      : '/workspaces'
  const doneTo = workspaceId ? wsHref(workspaceId, '/machines') : leaveTo

  const restart = useCallback(() => {
    setPending(null)
    setApproved(false)
    setError(null)
    setCode('')
    setFromLink(false)
    // The workspace goes too. Before the lookup and the choosing were split apart, every
    // successful lookup reset it; leaving it behind here means asking about a second machine
    // and being handed the workspace picked for the first one, already selected, which is a
    // machine going somewhere nobody chose for it. Caught in review of PR #266.
    setChosenWorkspaceId('')
  }, [])

  const lookUpCode = useCallback(
    async (typed: string) => {
      setError(null)
      setBusy(true)
      try {
        setPending(await getMachineLink(typed))
      } catch (err) {
        setError(errorText(err, t))
      }
      setBusy(false)
    },
    [t],
  )

  async function lookUp(e: FormEvent) {
    e.preventDefault()
    await lookUpCode(code)
  }

  // Arriving from the daemon's own link: look the code up once, so the first thing the person
  // sees is the machine that is asking rather than a box wanting the code they already have.
  //
  // A failed lookup deliberately leaves the form behind rather than a dead end — an expired or
  // mistyped code in an address is exactly the case where typing a fresh one is the answer.
  const attempted = useRef<string | null>(null)
  useEffect(() => {
    const carried = formatCode(params.get('code') ?? '')
    if (!isComplete(carried) || attempted.current === carried) return
    attempted.current = carried
    setCode(carried)
    setFromLink(true)
    void lookUpCode(carried)
  }, [params, lookUpCode])


  async function approve() {
    if (!pending || !workspaceId) return
    setError(null)
    setBusy(true)
    try {
      await approveMachineLink(pending.code, workspaceId)
      setApproved(true)
      // Approving no longer finishes the first steps (spec 003 FR-106). It used to, and that
      // dropped people into a workspace where every agent was offline: an approved machine has
      // its papers and no runtime yet — that comes with `armarius-daemon start`. So nothing is
      // written here. The window standing on the connect step hears `machine.linked` from the
      // server, marks this part done, and moves on by itself once the daemon reports in.
    } catch (err) {
      setError(errorText(err, t))
    }
    setBusy(false)
  }

  const labelCls = 'mb-1.5 block font-body text-body-sm font-medium text-ink'
  const buttonCls = 'btn btn-primary w-full'
  const ghostCls = 'btn btn-ghost w-full'
  const errorLine = (text: string) => (
    <p
      className="flex items-start gap-2 rounded-md border border-danger/30 bg-danger-soft px-3 py-2 font-body text-body-sm text-danger"
      role="alert"
    >
      <TriangleAlert className="w-4 h-4 mt-0.5 shrink-0" aria-hidden />
      <span className="min-w-0">{text}</span>
    </p>
  )
  // A notice the person should weigh before saying yes — gold, the colour of "this is yours".
  const noticeCls =
    'flex items-start gap-2 rounded-md border border-gold/30 bg-gold-soft px-3 py-2.5 font-body text-body-sm text-ink'

  return (
    <EntryFrame>
      <motion.div
        className="w-full max-w-[520px]"
        initial={{ opacity: 0, y: 8 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.2 }}
      >
        <div className="text-center mb-6">
          <span className="mx-auto mb-4 w-12 h-12 rounded-full bg-surface border border-line flex items-center justify-center">
            <Link2 className="w-5 h-5 text-sapphire-strong" aria-hidden />
          </span>
          <p className="eyebrow">{t('linkMachine.eyebrow')}</p>
          <h1 className="mt-2 font-display font-normal text-[30px] sm:text-[34px] leading-[1.1] tracking-[-0.03em] text-ink-strong">
            {t('linkMachine.title')}
          </h1>
          <p className="mt-2.5 font-body text-body-md text-ink-light">
            <WithCommands text={t('linkMachine.lead')} />
          </p>
        </div>

        <div className="surface shadow-[var(--shadow)] px-[18px] py-6 sm:p-8">
          {approved ? (
            <div className="text-center space-y-3">
              <span className="mx-auto w-12 h-12 rounded-full border border-success/30 bg-success-soft flex items-center justify-center">
                <Check className="w-6 h-6 text-success" aria-hidden />
              </span>
              <h2 className="font-display font-normal text-[24px] text-ink-strong">
                {t('linkMachine.doneTitle')}
              </h2>
              <p className="font-body text-body-md text-ink-light">
                {t('linkMachine.doneBody')}
              </p>
              <p className="font-body text-body-md text-ink-light">
                <WithCommands text={t('linkMachine.doneStart')} />
              </p>
              {inFirstSteps && (
                <p className="font-body text-body-sm text-ink-muted">
                  {t('linkMachine.doneFirstSteps')}
                </p>
              )}
              {inFirstSteps ? (
                // Mid first steps, the way on is back to them: the step that was waiting for this
                // machine is the next thing to do, and the workspace behind it is not ready yet.
                // Caught by the owner on 2026-10-26 — the machine list here led straight in.
                <div className="flex flex-col gap-1 pt-3">
                  <button
                    type="button"
                    // Carries what this page knows and the next one cannot yet read: a machine
                    // was approved a moment ago. Its row appears only once the daemon collects
                    // its papers, and the step must not show linking as undone until then.
                    onClick={() => navigate('/onboarding', { state: { machineApproved: true } })}
                    className={buttonCls}
                  >
                    {t('linkMachine.doneBackToFirstSteps')}
                  </button>
                  <button type="button" onClick={restart} className={ghostCls}>
                    {t('linkMachine.doneAgain')}
                  </button>
                </div>
              ) : (
                <div className="flex flex-col gap-1 pt-3">
                  <button type="button" onClick={restart} className={buttonCls}>
                    {t('linkMachine.doneAgain')}
                  </button>
                  <button type="button" onClick={() => navigate(doneTo)} className={ghostCls}>
                    {t('linkMachine.doneLeave')}
                  </button>
                </div>
              )}
            </div>
          ) : pending ? (
            <div className="space-y-5">
              <div>
                <p className={labelCls}>{t('linkMachine.machineHeading')}</p>
                <div className="flex items-center gap-3 rounded-md bg-canvas-deep border border-line p-4">
                  <Laptop className="w-7 h-7 shrink-0 text-sapphire-strong" strokeWidth={1.4} aria-hidden />
                  <div className="min-w-0">
                    <p className="font-display text-[20px] font-normal leading-tight text-ink-strong break-words">
                      {pending.hostname || t('linkMachine.hostnameUnknown')}
                    </p>
                    <p className="mt-0.5 font-mono text-mono-sm text-ink-muted break-words">
                      {pending.platform} · {pending.daemon_version}
                    </p>
                  </div>
                </div>
              </div>

              <p className="font-body text-body-sm text-ink-light flex items-start gap-2">
                <ShieldQuestion className="w-4 h-4 mt-0.5 shrink-0" aria-hidden />
                <span>{t('linkMachine.claimNotice')}</span>
              </p>

              {/* Only when the code arrived on the address. Someone who typed it read it off
                  their own terminal seconds ago and needs no telling; someone who followed a
                  link has nothing but the link, and a link is the one thing another person
                  can send them. */}
              {fromLink && (
                <p className={noticeCls}>
                  <ShieldQuestion className="w-4 h-4 mt-0.5 shrink-0 text-gold" aria-hidden />
                  <span className="min-w-0">
                    <WithCommands text={t('linkMachine.fromLinkNotice')} />
                  </span>
                </p>
              )}

              {workspaces.length === 0 ? (
                errorLine(t('linkMachine.noWorkspace'))
              ) : (
                <div>
                  <label className={labelCls} htmlFor="link-workspace">
                    {t('linkMachine.workspaceLabel')}
                  </label>
                  <Dropdown
                    id="link-workspace"
                    size="sm"
                    value={workspaceId}
                    onChange={setChosenWorkspaceId}
                    items={workspaces.map((ws) => ({ value: ws.id, label: ws.name }))}
                  />
                </div>
              )}

              {error && errorLine(error)}

              {/* One line, right where the yes is given (FR-013b): a run on this machine is
                  granted whatever it asks for, because nobody is there to be asked. */}
              <p className={noticeCls} data-testid="link-unattended-warning">
                <TriangleAlert className="w-4 h-4 mt-0.5 shrink-0 text-gold" aria-hidden />
                <span className="min-w-0">{t('linkMachine.unattendedWarning')}</span>
              </p>

              <div className="space-y-1">
                <button
                  type="button"
                  onClick={approve}
                  disabled={busy || !workspaceId}
                  className={buttonCls}
                >
                  {t('linkMachine.approveButton')}
                </button>
                {remaining !== null && (
                  <p className="pt-1 text-center font-body text-body-sm text-ink-muted">
                    {t('linkMachine.expiresIn', { count: remaining })}
                  </p>
                )}
                <button type="button" onClick={restart} className={ghostCls}>
                  <ArrowLeft className="w-4 h-4" aria-hidden />
                  {t('linkMachine.otherCode')}
                </button>
              </div>
            </div>
          ) : busy && fromLink ? (
            <p className="flex items-center justify-center gap-2 font-body text-body-md text-ink-light py-6" role="status">
              <Loader2 className="w-4 h-4 animate-spin" aria-hidden />
              {t('linkMachine.checking')}
            </p>
          ) : (
            <form onSubmit={lookUp} className="space-y-4">
              <div>
                <label className={labelCls} htmlFor="link-code">
                  {t('linkMachine.codeLabel')}
                </label>
                <input
                  id="link-code"
                  value={code}
                  onChange={(e) => setCode(formatCode(e.target.value))}
                  placeholder={t('linkMachine.codePlaceholder')}
                  autoFocus
                  autoComplete="off"
                  spellCheck={false}
                  className={cn(
                    'field',
                    'min-h-[52px] text-center font-mono text-[20px] tracking-[0.3em] uppercase',
                    'placeholder:font-body placeholder:text-body-md placeholder:tracking-normal placeholder:normal-case',
                  )}
                />
              </div>

              {error && errorLine(error)}

              <button type="submit" disabled={busy || !isComplete(code)} className={buttonCls}>
                {t('linkMachine.lookupButton')}
              </button>
            </form>
          )}
        </div>

        <button
          type="button"
          onClick={() => navigate(leaveTo)}
          className={cn(ghostCls, 'mt-4')}
        >
          <ArrowLeft className="w-4 h-4" aria-hidden />
          {inFirstSteps ? t('linkMachine.backToFirstSteps') : t('linkMachine.back')}
        </button>
      </motion.div>
    </EntryFrame>
  )
}
