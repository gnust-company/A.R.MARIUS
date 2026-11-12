import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Paperclip } from 'lucide-react';

import { downloadArtifact, listArtifacts, listComments, type ArtifactDTO, type CommentDTO } from '@/lib/api';
import { currentOnly } from '@/lib/artifactVersions';
import { errorText } from '@/lib/errors';
import { agentsOf } from '@/lib/workspaceScope';
import { useAppStore } from '@/store/appStore';

interface Props {
  taskId: string;
  workspaceId?: string;
}

/**
 * What the patron is being asked to sign, shown where they are asked.
 *
 * The letter used to say "the Leader passed this, sign to close" and offer two buttons. The
 * work itself, and whatever the Leader wrote when passing it, were a screen away — so the
 * honest way to sign was to leave the inbox first, and the easy way was not to look
 * (found 2026-11-12 while signing two tasks as the patron).
 *
 * Read-only and small on purpose: the current version of each published file, and the last
 * thing said on the task's thread. The task screen is still one link away for the rest.
 */
export default function OutputEvidence({ taskId, workspaceId }: Props) {
  const { t } = useTranslation();
  const everyone = useAppStore((s) => s.mariuses);
  const [artifacts, setArtifacts] = useState<ArtifactDTO[] | null>(null);
  const [lastWord, setLastWord] = useState<CommentDTO | null>(null);
  const [fetching, setFetching] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    // Two reads that fail apart: a thread that will not load is no reason to hide the files.
    listArtifacts(taskId)
      .then((rows) => {
        if (alive) setArtifacts(rows);
      })
      .catch((e: unknown) => {
        if (alive) setError(errorText(e, t));
      });
    listComments(taskId)
      .then((rows) => {
        if (alive) setLastWord(rows.length ? rows[rows.length - 1] : null);
      })
      .catch(() => {});
    return () => {
      alive = false;
    };
  }, [taskId, t]);

  const save = async (artifact: ArtifactDTO) => {
    setFetching(artifact.id);
    setError(null);
    try {
      const blob = await downloadArtifact(taskId, artifact.id);
      const href = URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = href;
      link.download = artifact.name || 'artifact';
      link.click();
      URL.revokeObjectURL(href);
    } catch (e) {
      setError(errorText(e, t));
    } finally {
      setFetching(null);
    }
  };

  if (artifacts === null && !error) return null;

  const current = currentOnly(artifacts ?? []);
  const author = lastWord?.author_marius_id
    ? agentsOf(everyone, workspaceId).find((m) => m.id === lastWord.author_marius_id)?.name
    : undefined;

  return (
    <section className="mt-6" data-testid="inbox-output-evidence">
      <h3 className="eyebrow">{t('inbox.evidence.title')}</h3>
      {current.length === 0 ? (
        <p className="mt-2 font-body text-body-sm text-ink-light">{t('inbox.evidence.none')}</p>
      ) : (
        <ul className="mt-2 flex flex-col gap-2">
          {current.map(({ artifact, version, of }) => (
            <li key={artifact.id}>
              {artifact.kind === 'link' ? (
                <a
                  href={artifact.uri || '#'}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="group flex min-h-[44px] items-center gap-3 rounded-md border border-line bg-field px-3 py-2 transition-colors hover:border-sapphire"
                >
                  <Paperclip className="h-4 w-4 shrink-0 text-ink-muted" aria-hidden />
                  <span className="min-w-0 flex-1 truncate font-body text-[13px] text-ink">{artifact.name}</span>
                </a>
              ) : (
                <button
                  type="button"
                  onClick={() => void save(artifact)}
                  disabled={fetching === artifact.id}
                  className="group flex min-h-[44px] w-full items-center gap-3 rounded-md border border-line bg-field px-3 py-2 text-left transition-colors hover:border-sapphire disabled:opacity-60"
                >
                  <Paperclip className="h-4 w-4 shrink-0 text-ink-muted" aria-hidden />
                  <span className="min-w-0 flex-1 truncate font-body text-[13px] text-ink">{artifact.name}</span>
                  {of > 1 && (
                    <span className="shrink-0 font-mono text-[11px] text-ink-muted">
                      {t('inbox.evidence.version', { version, of })}
                    </span>
                  )}
                </button>
              )}
            </li>
          ))}
        </ul>
      )}
      {error && (
        <p className="mt-2 font-body text-[12px] text-danger" role="alert">
          {error}
        </p>
      )}
      {lastWord && (
        <div className="mt-4">
          <h3 className="eyebrow">
            {author ? t('inbox.evidence.lastWordBy', { name: author }) : t('inbox.evidence.lastWord')}
          </h3>
          <p className="mt-2 max-h-56 overflow-y-auto whitespace-pre-line break-words rounded-md border border-line bg-surface px-3.5 py-3 font-body text-[13px] leading-[1.7] text-ink-light">
            {lastWord.body}
          </p>
        </div>
      )}
    </section>
  );
}
