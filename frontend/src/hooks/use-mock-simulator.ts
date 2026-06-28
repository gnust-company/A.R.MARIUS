import { useEffect } from 'react'
import { useMockStore } from '@/store/mockStore'

/**
 * Simulated Hybrid SSE — workspace control-plane channel (FE-1).
 *
 * Mounted once at the app root. It marks the SSE link "connected" and, on an
 * interval, decays agent liveness (ONLINE → idle/checking → offline and back)
 * so the directory dots and the TopBar status feel alive on pure mock data —
 * exactly the behaviour the real `/workspaces/{ws}/events` stream will push.
 *
 * Honours `prefers-reduced-motion`: when the user opts out of motion we keep the
 * link "connected" but stop the churn so nothing flickers.
 */
export function useMockSimulator(intervalMs = 4500) {
  const setSseConnected = useMockStore((s) => s.setSseConnected)
  const simulateLivenessTick = useMockStore((s) => s.simulateLivenessTick)

  useEffect(() => {
    setSseConnected(true)

    const reduced =
      typeof window !== 'undefined' &&
      window.matchMedia?.('(prefers-reduced-motion: reduce)').matches

    if (reduced) {
      return () => setSseConnected(false)
    }

    const id = window.setInterval(simulateLivenessTick, intervalMs)
    return () => {
      window.clearInterval(id)
      setSseConnected(false)
    }
  }, [setSseConnected, simulateLivenessTick, intervalMs])
}
