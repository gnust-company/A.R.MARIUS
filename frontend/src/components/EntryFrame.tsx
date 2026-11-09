// The frame around the pages a person meets before they are inside a workspace: signing in,
// the first steps, picking a workspace, approving a machine. None of them has the sidebar —
// at that point there is no workspace for it to describe — so the brand mark that the sidebar
// carries everywhere else has to be carried here instead, or these pages read as belonging to
// some other product. The theme switch rides along for the same reason: the sidebar is where
// it lives inside a workspace, and these pages have no sidebar.

import type { ReactNode } from 'react'
import { Brand } from '@/components/Brand'
import ThemeSwitch from '@/components/ThemeSwitch'
import { cn } from '@/lib/utils'

/** The Armarius mark (sigil + wordmark), the same one the sidebar shows. `lg` sets it larger
 *  for a page whose only heading is the brand itself. */
export function Wordmark({ size = 'md', className }: { size?: 'md' | 'lg'; className?: string }) {
  return (
    <Brand
      className={cn(
        size === 'lg' && '[&>svg]:w-12 [&>svg]:h-12 [&_span>span:first-child]:text-[22px]',
        className,
      )}
    />
  )
}

/** The quiet sky behind every entry page: two faint glows in the theme's sapphire and gold,
 *  and a pair of crossed orbits echoing the sigil. Decoration only — never read, never hit. */
function Sky() {
  return (
    <div aria-hidden className="pointer-events-none absolute inset-0 overflow-hidden">
      <div
        className="absolute inset-0"
        style={{
          background:
            'radial-gradient(60% 45% at 78% 0%, oklch(var(--sapphire) / .12), transparent 70%),' +
            'radial-gradient(45% 40% at 8% 100%, oklch(var(--gold) / .08), transparent 70%)',
        }}
      />
      <svg
        viewBox="0 0 400 400"
        className="absolute -right-40 -top-24 w-[640px] h-[640px] text-line-strong opacity-40 sm:-right-24"
      >
        <g fill="none" stroke="currentColor" strokeWidth="0.6">
          <ellipse cx="200" cy="200" rx="180" ry="72" transform="rotate(32 200 200)" />
          <ellipse cx="200" cy="200" rx="180" ry="72" transform="rotate(-32 200 200)" />
          <circle cx="200" cy="200" r="118" strokeDasharray="2 6" />
        </g>
        <circle cx="352" cy="104" r="3" className="fill-gold" opacity=".7" />
      </svg>
    </div>
  )
}

/** Canvas page with the brand and the theme switch in a slim top bar, the content under it. */
export default function EntryFrame({
  children,
  aside,
  center = false,
}: {
  children: ReactNode
  /** Something small for the right end of the top bar, before the theme switch. */
  aside?: ReactNode
  /** Centre the content vertically (a single short card, as on sign-in). */
  center?: boolean
}) {
  return (
    <div className="relative isolate min-h-[100dvh] flex flex-col">
      <Sky />
      <header className="relative shrink-0 border-b border-line bg-canvas/70 backdrop-blur-md">
        <div className="mx-auto w-full max-w-[1168px] h-16 sm:h-[72px] flex items-center justify-between gap-3 px-4 sm:px-6">
          <Brand />
          <div className="flex items-center gap-2 sm:gap-3">
            {aside}
            <ThemeSwitch compact className="sm:hidden" />
            <ThemeSwitch className="hidden sm:flex" />
          </div>
        </div>
      </header>
      <main
        className={cn(
          'relative flex-1 w-full flex flex-col items-center px-4 sm:px-6 pb-16',
          center ? 'justify-center pt-8 sm:pt-12' : 'pt-7 sm:pt-12 xl:pt-16',
        )}
      >
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
            className="font-mono text-mono-sm text-sapphire-strong bg-canvas-deep border border-line rounded-xs px-1 py-px break-words"
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
