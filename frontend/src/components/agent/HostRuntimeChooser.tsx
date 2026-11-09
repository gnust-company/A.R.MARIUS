// The way a host with nowhere to work gets somewhere (spec 003 FR-128).
//
// Only the host, and only while it has no runtime: either it never had one — the first steps
// were skipped — or its machine was taken out of the workspace. Neither is moving it, because
// there is nothing to move it from. Every other agent keeps the runtime it was made on
// (FR-007), which is why the parent shows this block for the host alone and the server refuses
// anyone else with `placement_is_fixed`.
//
// Same list and same rule as the first steps (FR-125), and nothing sent but the runtime: the
// host's instructions are edited on their own tab.

import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Loader2, Server } from 'lucide-react'

import { ApiError, errorText } from '@/lib/errors'
import { currentRuntimeChoice } from '@/lib/runtimeChoice'
import { WORKPLACES_REPORTED } from '@/lib/sse'
import { onWorkspaceEvent } from '@/hooks/use-workspace-events'
import { useRuntimeOffer } from '@/hooks/use-runtime-offer'
import { useAppStore } from '@/store/appStore'
import RuntimePicker from './RuntimePicker'

export default function HostRuntimeChooser({
  workspaceId,
  hostId,
  hostName,
}: {
  workspaceId: string
  hostId: string
  hostName: string
}) {
  const { t } = useTranslation()
  const placeHost = useAppStore((s) => s.placeHost)
  const refreshMariuses = useAppStore((s) => s.refreshMariuses)
  const offer = useRuntimeOffer(workspaceId)
  const reloadOffer = offer.reload
  const [picked, setPicked] = useState<string | null>(null)
  const chosen = currentRuntimeChoice(offer.ready, picked)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  // A machine starting or stopping changes what can be picked. The layout already holds the
  // workspace stream open; this listens on it rather than opening a second (Constitution IV).
  useEffect(
    () =>
      onWorkspaceEvent((event) => {
        if (event.type === WORKPLACES_REPORTED) reloadOffer()
      }),
    [reloadOffer],
  )

  async function choose() {
    if (!chosen) return
    setError(null)
    setBusy(true)
    try {
      // On success the store holds the host with its runtime, and the parent stops showing
      // this block.
      await placeHost(workspaceId, hostId, chosen)
    } catch (err) {
      setError(errorText(err, t))
      if (err instanceof ApiError && err.code === 'agent_already_placed') {
        // Chosen somewhere else a moment ago: read the agent again so the page shows where.
        void refreshMariuses(workspaceId).catch(() => {})
      } else if (err instanceof ApiError && err.code === 'placement_not_ready') {
        reloadOffer()
      }
      setBusy(false)
    }
  }

  return (
    <div className="space-y-4">
      <div className="flex items-start gap-3">
        {/* Gold: the host cannot work until somebody picks — it is waiting on the patron. */}
        <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full border border-gold/35 bg-gold-soft text-gold">
          <Server className="h-[18px] w-[18px]" aria-hidden />
        </span>
        <div className="min-w-0">
          <h2 className="font-display text-[22px] font-normal leading-tight tracking-[-0.02em] text-ink-strong">
            {t('agentDetail.chooseRuntime.title', { name: hostName })}
          </h2>
          <p className="mt-1 font-body text-body-md text-ink-light">
            {t('agentDetail.chooseRuntime.lead', { name: hostName })}
          </p>
        </div>
      </div>
      <RuntimePicker
        ready={offer.ready}
        machines={offer.machines}
        chosen={chosen}
        onChoose={setPicked}
        loading={offer.loading}
        disabled={busy}
      />
      {error && (
        <p className="font-body text-body-sm text-danger" role="alert">
          {error}
        </p>
      )}
      <button
        type="button"
        onClick={choose}
        disabled={busy || !chosen}
        className="btn btn-primary"
      >
        {busy && <Loader2 className="h-4 w-4 animate-spin" aria-hidden />}
        {t('agentDetail.chooseRuntime.button')}
      </button>
    </div>
  )
}
