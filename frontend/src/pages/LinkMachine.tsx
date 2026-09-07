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
import { ArrowLeft, Check, Laptop, ShieldQuestion } from 'lucide-react'

import { approveMachineLink, getMachineLink, type PendingMachineLinkDTO } from '@/lib/api'
import { errorText } from '@/lib/errors'
import { useAppStore } from '@/store/appStore'
import VellumPanel from '@/components/VellumPanel'
import { cn, wsHref } from '@/lib/utils'

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

  const [code, setCode] = useState('')
  const [pending, setPending] = useState<PendingMachineLinkDTO | null>(null)
  const [workspaceId, setWorkspaceId] = useState('')
  const [approved, setApproved] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  // The code came off the address rather than out of somebody's fingers, which changes one
  // thing on this screen: what the warning has to say. A person who typed the code was
  // reading it off their own terminal a moment ago; a person who followed a link has no such
  // evidence and needs telling so.
  const [fromLink, setFromLink] = useState(false)

  useEffect(() => {
    void hydrateWorkspaces().catch(() => {})
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
  const leaveTo = activeWorkspaceId ? wsHref(activeWorkspaceId, '/machines') : '/workspaces'
  const doneTo = workspaceId ? wsHref(workspaceId, '/machines') : leaveTo

  const restart = useCallback(() => {
    setPending(null)
    setApproved(false)
    setError(null)
    setCode('')
    setFromLink(false)
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

  // The workspace to approve into, chosen as soon as there is one to choose. This cannot be
  // done inside the lookup: on a cold load the list is still arriving while the code is being
  // looked up, and a machine found before the list lands would leave the approve button
  // disabled with a workspace visibly selected in the box beside it.
  useEffect(() => {
    if (!pending || workspaceId) return
    const first = activeWorkspaceId ?? workspaces[0]?.id ?? ''
    if (first) setWorkspaceId(first)
  }, [pending, workspaceId, activeWorkspaceId, workspaces])

  async function approve() {
    if (!pending || !workspaceId) return
    setError(null)
    setBusy(true)
    try {
      await approveMachineLink(pending.code, workspaceId)
      setApproved(true)
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
  const labelCls = 'block font-body text-body-sm text-ink-light mb-1'
  const buttonCls = cn(
    'w-full px-4 py-2 rounded-md font-body text-body-md transition-colors',
    'bg-terracotta text-white hover:bg-terracotta-light disabled:opacity-50',
  )

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
        <h1 className="font-display text-display-md text-ink text-center mb-2">
          {t('linkMachine.title')}
        </h1>
        <p className="font-body text-body-sm text-ink-light text-center mb-8">
          {t('linkMachine.lead')}
        </p>

        <VellumPanel hover={false}>
          {approved ? (
            <div className="text-center space-y-4">
              <Check className="w-10 h-10 mx-auto text-terracotta" aria-hidden />
              <h2 className="font-display text-display-sm text-ink">
                {t('linkMachine.doneTitle')}
              </h2>
              <p className="font-body text-body-sm text-ink-light">
                {t('linkMachine.doneBody')}
              </p>
              <div className="flex flex-col gap-2 pt-2">
                <button type="button" onClick={restart} className={buttonCls}>
                  {t('linkMachine.doneAgain')}
                </button>
                <button
                  type="button"
                  onClick={() => navigate(doneTo)}
                  className="font-body text-body-sm text-ink-muted hover:text-ink transition-colors"
                >
                  {t('linkMachine.doneLeave')}
                </button>
              </div>
            </div>
          ) : pending ? (
            <div className="space-y-5">
              <div className="flex items-start gap-3">
                <Laptop className="w-5 h-5 mt-0.5 text-ink-light shrink-0" aria-hidden />
                <div className="min-w-0">
                  <h2 className="font-display text-display-sm text-ink">
                    {t('linkMachine.machineHeading')}
                  </h2>
                  <p className="font-body text-body-md text-ink break-words">
                    {pending.hostname || t('linkMachine.hostnameUnknown')}
                  </p>
                  <p className="font-body text-body-sm text-ink-muted">
                    {pending.platform} · {pending.daemon_version}
                  </p>
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
                <p className="font-body text-body-sm text-terracotta flex items-start gap-2">
                  <ShieldQuestion className="w-4 h-4 mt-0.5 shrink-0" aria-hidden />
                  <span>{t('linkMachine.fromLinkNotice')}</span>
                </p>
              )}

              {remaining !== null && (
                <p className="font-body text-body-sm text-ink-muted">
                  {t('linkMachine.expiresIn', { count: remaining })}
                </p>
              )}

              {workspaces.length === 0 ? (
                <p className="font-body text-body-sm text-terracotta" role="alert">
                  {t('linkMachine.noWorkspace')}
                </p>
              ) : (
                <div>
                  <label className={labelCls} htmlFor="link-workspace">
                    {t('linkMachine.workspaceLabel')}
                  </label>
                  <select
                    id="link-workspace"
                    value={workspaceId}
                    onChange={(e) => setWorkspaceId(e.target.value)}
                    className={inputCls}
                  >
                    {workspaces.map((ws) => (
                      <option key={ws.id} value={ws.id}>
                        {ws.name}
                      </option>
                    ))}
                  </select>
                </div>
              )}

              {error && (
                <p className="font-body text-body-sm text-terracotta" role="alert">
                  {error}
                </p>
              )}

              <button
                type="button"
                onClick={approve}
                disabled={busy || !workspaceId}
                className={buttonCls}
              >
                {t('linkMachine.approveButton')}
              </button>
              <button
                type="button"
                onClick={restart}
                className="w-full font-body text-body-sm text-ink-muted hover:text-ink transition-colors flex items-center justify-center gap-1"
              >
                <ArrowLeft className="w-4 h-4" aria-hidden />
                {t('linkMachine.otherCode')}
              </button>
            </div>
          ) : busy && fromLink ? (
            <p className="font-body text-body-sm text-ink-light text-center py-4">
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
                  className={cn(inputCls, 'text-center tracking-[0.3em] uppercase')}
                />
              </div>

              {error && (
                <p className="font-body text-body-sm text-terracotta" role="alert">
                  {error}
                </p>
              )}

              <button type="submit" disabled={busy || !isComplete(code)} className={buttonCls}>
                {t('linkMachine.lookupButton')}
              </button>
            </form>
          )}
        </VellumPanel>

        <button
          type="button"
          onClick={() => navigate(leaveTo)}
          className="mt-6 w-full text-center font-body text-body-sm text-ink-muted hover:text-ink transition-colors"
        >
          {t('linkMachine.back')}
        </button>
      </motion.div>
    </div>
  )
}
