// A server refusal, and the patron's copy of it.
//
// The API answers a refusal with a cause **code plus its parameters** rather than a
// finished sentence, because the very same refusal is also read by an agent — and an agent
// has no interface language to pick from, so its copy is English (Constitution VII,
// FR-084a). `errorText` builds the screen's half from the same code.
//
// This lives below both `api.ts` and `auth.ts` and imports neither. `auth.ts` is kept free
// of any dependency on `api.ts` so the request wrapper there can read tokens without an
// import cycle — which is exactly why the refusal type cannot live in `api.ts`: the login
// screen would then be the one page in the app still showing the agent's English.

import type { TFunction } from 'i18next'

export class ApiError extends Error {
  status?: number
  /** The refusal's cause code (FR-084a). The screen builds its own sentence from this;
   *  `message` is the server's English rendering, kept as the fallback for a code this
   *  build has no phrase for yet. */
  code?: string
  params?: Record<string, string>
  constructor(detail: string, status?: number, code?: string, params?: Record<string, string>) {
    super(detail)
    this.name = 'ApiError'
    this.status = status
    this.code = code
    this.params = params
  }
}

/** Read a refusal off a failed response and throw it. One place, because every verb in
 *  `api.ts` used to parse the body itself and they had drifted into six copies of it. */
export async function throwApiError(res: Response): Promise<never> {
  let detail = `${res.status} ${res.statusText}`
  let code: string | undefined
  let params: Record<string, string> | undefined
  try {
    const data = await res.json()
    if (data?.detail) detail = typeof data.detail === 'string' ? data.detail : detail
    if (typeof data?.code === 'string') code = data.code
    if (data?.params && typeof data.params === 'object') params = data.params as Record<string, string>
  } catch {
    // non-JSON error body — keep the status-line fallback
  }
  throw new ApiError(detail, res.status, code, params)
}

/** The sentence to put on screen. A code this build has no phrase for falls back to the
 *  server's English: a refusal that reads a little oddly still tells the patron what was
 *  refused, and a blank one tells them nothing. */
export function errorText(e: unknown, t: TFunction): string {
  if (e instanceof ApiError && e.code) {
    const key = `errors.${e.code}`
    const rendered = t(key, { ...(e.params ?? {}) })
    if (rendered !== key) return rendered
  }
  if (e instanceof Error) return e.message
  return String(e)
}
