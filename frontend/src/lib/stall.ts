// The stall verdict, worded for the patron.
//
// The server stores *which* stall it is as a code and renders its own English copy for
// records and for agents (Constitution VII). The screen renders the same code from the
// phrase table below — the identical split the refusal codes use in `errors.ts`.
//
// An unknown code yields `undefined` rather than the raw code, so each caller falls back
// to its own generic label. A patron reading `stall_run_active` on a card learns nothing
// and mistrusts everything else on it.

import type { TFunction } from 'i18next'

export function stallText(code: string | undefined | null, t: TFunction): string | undefined {
  if (!code) return undefined
  const key = `stall.${code}`
  const rendered = t(key)
  return rendered === key ? undefined : rendered
}
