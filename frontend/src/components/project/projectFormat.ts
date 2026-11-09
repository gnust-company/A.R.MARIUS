// Small formatting helpers shared by the project index and the in-project header.
import type { Project } from '@/store/appStore';

/** A date as the reader's locale writes it. */
export function formatDate(iso: string | undefined, language: string): string | null {
  if (!iso) return null;
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return null;
  return date.toLocaleDateString(language.startsWith('vi') ? 'vi-VN' : 'en-GB');
}

/** The short code drawn in the project's folio circle: its KEY, or the name's first letters. */
export function projectCode(project: Pick<Project, 'key' | 'name'>): string {
  if (project.key) return project.key;
  return (project.name || '?').replace(/[^\p{L}\p{N}]/gu, '').slice(0, 4).toUpperCase();
}
