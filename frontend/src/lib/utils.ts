import { clsx, type ClassValue } from "clsx"
import { twMerge } from "tailwind-merge"

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs))
}

/**
 * Build a URL for a page *inside* a workspace. Every in-workspace route lives under
 * `/w/:workspaceId/…` so a hard refresh restores the right workspace (and its skills).
 * `sub` is the workspace-relative path, e.g. `wsHref(id, '/skills')` → `/w/<id>/skills`.
 * Falls back to `sub` when no workspace id is known (shouldn't happen inside the Layout).
 */
export function wsHref(workspaceId: string | null | undefined, sub = ''): string {
  const s = sub && !sub.startsWith('/') ? `/${sub}` : sub
  if (!workspaceId) return s || '/workspaces'
  return `/w/${workspaceId}${s === '/' ? '' : s}`
}

/**
 * Copy text to the clipboard, resilient to insecure contexts.
 * `navigator.clipboard` only exists on HTTPS / localhost, so on a plain-http LAN origin
 * (e.g. http://192.168.x.x:3000) it is `undefined` and the modern call silently fails —
 * which is exactly why the "Copy" buttons did nothing over the LAN. We fall back to the
 * legacy `document.execCommand('copy')` via an off-screen <textarea>. Returns true on success.
 */
export async function copyToClipboard(text: string): Promise<boolean> {
  if (typeof navigator !== 'undefined' && navigator.clipboard && window.isSecureContext) {
    try {
      await navigator.clipboard.writeText(text)
      return true
    } catch {
      // fall through to the legacy path below
    }
  }
  try {
    const ta = document.createElement('textarea')
    ta.value = text
    ta.setAttribute('readonly', '')
    ta.style.position = 'fixed'
    ta.style.top = '-9999px'
    ta.style.opacity = '0'
    document.body.appendChild(ta)
    ta.focus()
    ta.select()
    const ok = document.execCommand('copy')
    document.body.removeChild(ta)
    return ok
  } catch {
    return false
  }
}
