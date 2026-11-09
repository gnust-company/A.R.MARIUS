// The frame around the pages a person meets before they are inside a workspace: signing in,
// the first steps, picking a workspace, approving a machine. None of them has the sidebar —
// at that point there is no workspace for it to describe — so the brand mark that the sidebar
// carries everywhere else has to be carried here instead, or these pages read as belonging to
// some other product.

import type { ReactNode } from 'react'
import { cn } from '@/lib/utils'

/** "Armarius" with the gilt initial, the same mark the sidebar shows: the "A" doubles as the
 *  logo and the wordmark continues with "rmarius", so the letter is never printed twice.
 *  Gold is decoration here, not text the reader depends on — the word still reads in ink. */
export function Wordmark({ size = 'md', className }: { size?: 'md' | 'lg'; className?: string }) {
  const large = size === 'lg'
  return (
    <span className={cn('inline-flex items-baseline select-none', className)} aria-label="Armarius">
      <span
        aria-hidden
        className="leading-none"
        style={{
          fontFamily: "'Cinzel Decorative', 'Cinzel', serif",
          fontSize: large ? '46px' : '30px',
          color: '#D4A843',
          fontWeight: 700,
          textShadow: '1px 1px 0 rgba(158, 74, 44, 0.18)',
        }}
      >
        A
      </span>
      <span
        aria-hidden
        className={cn(
          'font-display font-medium text-ink tracking-tight leading-none',
          large ? 'text-[38px]' : 'text-[24px]',
        )}
      >
        rmarius
      </span>
    </span>
  )
}

/** Vellum page with the wordmark in a slim top bar and the content centred under it. */
export default function EntryFrame({
  children,
  aside,
}: {
  children: ReactNode
  /** Something small for the right end of the top bar, if the page has one. */
  aside?: ReactNode
}) {
  return (
    <div className="min-h-[100dvh] bg-vellum flex flex-col">
      <header className="h-16 shrink-0 flex items-center justify-between gap-3 px-4 sm:px-6 xl:px-9">
        <Wordmark />
        {aside}
      </header>
      <main className="flex-1 w-full flex flex-col items-center px-4 sm:px-6 pt-2 sm:pt-8 pb-16">
        {children}
      </main>
    </div>
  )
}

/** Copy that carries commands between backticks — `armarius-daemon login` — rendered with the
 *  commands set in mono, so a person can tell at a glance which words to type. The backticks
 *  live in the translations because the commands are the same in every language. */
export function WithCommands({ text }: { text: string }) {
  const parts = text.split('`')
  return (
    <>
      {parts.map((part, i) =>
        i % 2 === 1 ? (
          <code
            key={i}
            className="font-mono text-mono-sm text-ink bg-inset border border-line rounded px-1 py-px break-words"
          >
            {part}
          </code>
        ) : (
          // A span, not a Fragment: the dev build's inspector plugin stamps an attribute on
          // every JSX element, and React warns when a Fragment is given one.
          <span key={i}>{part}</span>
        ),
      )}
    </>
  )
}
