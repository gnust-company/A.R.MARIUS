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
