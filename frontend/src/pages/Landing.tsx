import { useEffect, useState, type ReactNode } from 'react'
import { useNavigate } from 'react-router'
import {
  ArrowRight,
  ChevronDown,
  Send,
  Users,
  Eye,
  Feather,
  Monitor,
  Database,
  FileText,
  Zap,
  FlaskConical,
  Scroll,
  CandlestickChart,
} from 'lucide-react'
import { cn } from '@/lib/utils'

/*
 * The public front page, on the same light "Xưởng sáng" vellum as the app it leads into, so
 * stepping from here into a workspace does not feel like walking into a different product.
 *
 * The marketing copy is deliberately English and kept out of i18n. The paintings are framed
 * illustrations on the page rather than dark full-bleed backdrops, and nothing here waits on a
 * scroll animation to become visible: the earlier pinned GSAP scenes hid their text at opacity 0
 * until scrolled, which left it unreadable in any view that never scrolled (previews, print,
 * full-page captures) and fought prefers-reduced-motion.
 */

/** Smooth-scroll only for visitors who have not asked the system for reduced motion. */
function scrollBehavior(): ScrollBehavior {
  return window.matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth'
}

function scrollToSection(id: string) {
  document.getElementById(id)?.scrollIntoView({ behavior: scrollBehavior() })
}

/** The app's wordmark: gilt Cinzel "A" as the mark, Fraunces for the rest (Cinzel has no
 *  Vietnamese glyphs, so it is kept to this single letter). */
function Wordmark({ size }: { size: 'header' | 'hero' }) {
  const hero = size === 'hero'
  return (
    <span className="inline-flex items-baseline leading-none">
      <span
        aria-hidden="true"
        className="text-gold"
        style={{
          fontFamily: "'Cinzel Decorative', 'Cinzel', serif",
          fontWeight: 700,
          fontSize: hero ? '1.12em' : '1.25em',
          // A hairline terracotta shadow keeps the gilt letter crisp against light vellum.
          textShadow: '1px 1px 0 rgba(158, 74, 44, 0.28)',
        }}
      >
        A
      </span>
      <span aria-hidden="true" className="font-display font-medium text-ink tracking-tight">
        rmarius
      </span>
      <span className="sr-only">Armarius</span>
    </span>
  )
}

/** A painting on the page: rounded, bordered, never a backdrop under text. */
function Framed({
  src,
  alt,
  className,
  imgClassName,
  eager = false,
}: {
  src: string
  alt: string
  className?: string
  imgClassName?: string
  eager?: boolean
}) {
  return (
    <figure className={cn('overflow-hidden rounded-xl border border-line bg-inset shadow-gilt', className)}>
      <img
        src={src}
        alt={alt}
        loading={eager ? 'eager' : 'lazy'}
        className={cn('block w-full h-full object-cover', imgClassName)}
      />
    </figure>
  )
}

function SectionHeading({ children, className }: { children: ReactNode; className?: string }) {
  return (
    <h2
      className={cn(
        'font-display font-medium text-ink text-[30px] sm:text-[36px] lg:text-[40px] leading-[1.15] tracking-tight',
        className
      )}
    >
      {children}
    </h2>
  )
}

/** Width cap shared by every section, so 1920px screens don't stretch lines edge to edge. */
const CONTAINER = 'mx-auto w-full max-w-[1240px] px-4 sm:px-6 xl:px-9'

/* ──────────────────────── Scene 1: Hero ──────────────────────── */
function HeroScene() {
  return (
    <section className="relative">
      <div className={cn(CONTAINER, 'pt-10 pb-16 sm:pt-14 lg:pt-20 lg:pb-24')}>
        <div className="grid grid-cols-1 lg:grid-cols-[minmax(0,5fr)_minmax(0,7fr)] items-center gap-10 lg:gap-14">
          <div className="text-center lg:text-left">
            <h1 className="text-[56px] sm:text-[72px] xl:text-[88px]">
              <Wordmark size="hero" />
            </h1>
            <p className="mt-5 font-display text-[20px] sm:text-[24px] leading-snug text-ink-light max-w-[30ch] mx-auto lg:mx-0">
              From medieval manuscripts to digital collaboration
            </p>
            <button
              type="button"
              onClick={() => scrollToSection('chamber')}
              className="mt-8 inline-flex min-h-[44px] items-center gap-2 rounded-md px-3 -mx-3 font-body text-body-md font-medium text-ink-light hover:text-ink hover:bg-inset transition-colors"
            >
              Scroll to begin
              <ChevronDown className="w-4 h-4" aria-hidden="true" />
            </button>
          </div>

          <Framed
            src="/hero-scriptorium.jpg"
            alt="Monks at work in a candle-lit monastery scriptorium"
            className="aspect-[16/10]"
            eager
          />
        </div>
      </div>
    </section>
  )
}

/* ──────────────────────── Scene 2: The Chamber ──────────────────────── */
const chamberLines = [
  'The Scriptorium was the heart of every great monastery — a silent workshop where knowledge was preserved by hand, word by word, page by page.',
  'Inside, the Patron prepared vellum and ink; scribes wrote with precision, illuminators brought gold and colour — each a master of their craft, working as one.',
  'That same spirit lives on today — not in stone corridors, but in code. Armarius carries the Scriptorium into the age of AI.',
]

function ChamberScene() {
  return (
    <section id="chamber" className="scroll-mt-16 bg-paper border-y border-line">
      <div className={cn(CONTAINER, 'py-16 lg:py-24')}>
        <div className="grid grid-cols-1 lg:grid-cols-2 items-center gap-10 lg:gap-16">
          <Framed
            src="/step-prepare.jpg"
            alt="A desk laid with vellum, ink and quills"
            className="aspect-[16/9] order-2 lg:order-1"
          />
          <div className="order-1 lg:order-2 max-w-[60ch] mx-auto lg:mx-0">
            {chamberLines.map((line, i) => (
              <div key={i}>
                {i > 0 && <div aria-hidden="true" className="my-7 h-px w-16 bg-gold" />}
                <p
                  className={cn(
                    'font-display leading-[1.5] text-[19px] sm:text-[21px]',
                    i === chamberLines.length - 1 ? 'text-ink' : 'text-ink-light'
                  )}
                  style={{ textWrap: 'pretty' }}
                >
                  {line}
                </p>
              </div>
            ))}
          </div>
        </div>
      </div>
    </section>
  )
}

/* ──────────────────────── Scene 3: The Characters ──────────────────────── */
const characters = [
  {
    image: '/char-armarius.jpg',
    name: 'Armarius, the Patron',
    description: 'He who prepares the materials and oversees all work',
  },
  {
    image: '/char-scribe.jpg',
    name: 'The Scribe',
    description: 'Expert in text, precision in every stroke',
  },
  {
    image: '/char-illuminator.jpg',
    name: 'The Illuminator',
    description: 'Artist who brings beauty and light',
  },
]

function CharactersScene() {
  return (
    <section id="characters" className="scroll-mt-16">
      <div className={cn(CONTAINER, 'py-16 lg:py-24')}>
        <SectionHeading className="text-center">The Characters</SectionHeading>

        <div className="mt-10 grid grid-cols-1 sm:grid-cols-3 gap-6 lg:gap-8 max-w-[420px] sm:max-w-none mx-auto">
          {characters.map((char) => (
            <article key={char.name} className="flex flex-col rounded-xl border border-line bg-paper overflow-hidden">
              <div className="aspect-[4/3] sm:aspect-[4/5] overflow-hidden border-b border-line bg-inset">
                <img
                  src={char.image}
                  alt={char.name}
                  loading="lazy"
                  className="block w-full h-full object-cover object-top"
                />
              </div>
              <div className="p-5">
                <h3 className="font-display font-medium text-ink text-[20px] leading-tight">{char.name}</h3>
                <p className="mt-1.5 font-body text-body-md text-ink-light">{char.description}</p>
              </div>
            </article>
          ))}
        </div>
      </div>
    </section>
  )
}

/* ──────────────────────── Scene 4: The Process ──────────────────────── */
const processSteps = [
  {
    number: '01',
    title: 'Prepare',
    medieval: 'Vellum, ink, and quills',
    modern: 'You prepare the project context',
    image: '/step-prepare.jpg',
  },
  {
    number: '02',
    title: 'Assign',
    medieval: 'Each scribe receives their task',
    modern: 'You task the agents',
    image: '/step-assign.jpg',
  },
  {
    number: '03',
    title: 'Collaborate',
    medieval: 'Many hands, one vision',
    modern: 'They collaborate in real-time',
    image: '/step-collaborate.jpg',
  },
  {
    number: '04',
    title: 'Inspect',
    medieval: 'No page leaves without approval',
    modern: 'You trace and approve',
    image: '/step-inspect.jpg',
  },
]

function ProcessScene() {
  return (
    <section id="process" className="scroll-mt-16 bg-paper border-y border-line">
      <div className={cn(CONTAINER, 'py-16 lg:py-24')}>
        <SectionHeading className="text-center">The Process of Creation</SectionHeading>

        {/* Timeline — alternating sides from md, a single column below. */}
        <div className="relative mt-12 max-w-5xl mx-auto">
          <div aria-hidden="true" className="absolute left-1/2 top-0 bottom-0 w-px bg-line-strong -translate-x-1/2 hidden md:block" />

          <ol className="flex flex-col gap-14 md:gap-20">
            {processSteps.map((step, i) => {
              const isEven = i % 2 === 0
              return (
                <li
                  key={step.number}
                  className={cn(
                    'relative flex flex-col md:items-center gap-6 md:gap-10',
                    isEven ? 'md:flex-row' : 'md:flex-row-reverse'
                  )}
                >
                  {/* Content side */}
                  <div className={cn('flex-1 min-w-0', isEven ? 'md:text-right' : 'md:text-left')}>
                    <span className="block font-display font-medium text-gold-ink text-[44px] sm:text-[56px] leading-none">
                      {step.number}
                    </span>
                    <h3 className="mt-2 font-display font-medium text-ink text-[22px]">{step.title}</h3>
                    <p className="mt-1.5 font-body text-body-md italic text-ink-light">&ldquo;{step.medieval}&rdquo;</p>
                    <p
                      className={cn(
                        'mt-3 flex items-center gap-2 font-body text-body-md font-medium text-ink',
                        isEven && 'md:justify-end'
                      )}
                    >
                      <ArrowRight className="w-4 h-4 shrink-0 text-gold-ink" aria-hidden="true" />
                      {step.modern}
                    </p>
                  </div>

                  {/* Center dot on the line */}
                  <div aria-hidden="true" className="hidden md:block w-3.5 h-3.5 shrink-0 rounded-full bg-gold ring-4 ring-paper z-10" />

                  {/* Image side */}
                  <div className="flex-1 min-w-0">
                    <Framed
                      src={step.image}
                      alt={step.title}
                      className={cn('aspect-[4/3] w-full md:max-w-[340px] shadow-none', isEven ? 'md:mr-auto' : 'md:ml-auto')}
                    />
                  </div>
                </li>
              )
            })}
          </ol>
        </div>
      </div>
    </section>
  )
}

/* ──────────────────────── Scene 5: The Parallel ──────────────────────── */
const parallelMappings = [
  { medievalIcon: Feather, medievalLabel: 'Vellum & Quill', modernLabel: 'Code Editor', modernIcon: Monitor },
  { medievalIcon: FlaskConical, medievalLabel: 'Ink & Gold Leaf', modernLabel: 'Data & Context', modernIcon: Database },
  { medievalIcon: Scroll, medievalLabel: 'Manuscript Pages', modernLabel: 'Task Artifacts', modernIcon: FileText },
  { medievalIcon: CandlestickChart, medievalLabel: 'Candlelight', modernLabel: 'Live Trace Stream', modernIcon: Zap },
]

function ParallelScene() {
  return (
    <section className="relative">
      <div className={cn(CONTAINER, 'py-16 lg:py-24')}>
        <SectionHeading className="text-center">Then and Now</SectionHeading>

        {/* Side by side only from xl: at 1024 the two-sided rows squeeze their labels onto two lines. */}
        <div className="mt-10 grid grid-cols-1 xl:grid-cols-2 items-center gap-10 xl:gap-14 max-w-3xl xl:max-w-none mx-auto">
          <Framed
            src="/parallel-split.jpg"
            alt="A monk illuminating a manuscript beside a developer at a bank of screens"
            className="aspect-[16/9]"
          />

          <ul className="flex flex-col gap-3">
            {parallelMappings.map((mapping) => {
              const MedievalIcon = mapping.medievalIcon
              const ModernIcon = mapping.modernIcon
              return (
                <li
                  key={mapping.medievalLabel}
                  className="grid grid-cols-[minmax(0,1fr)_auto_minmax(0,1fr)] items-center gap-3 sm:gap-5 rounded-xl border border-line bg-paper px-3 py-3.5 sm:px-5"
                >
                  {/* Medieval side */}
                  <div className="flex flex-col sm:flex-row-reverse items-center sm:justify-start gap-2 sm:gap-3 min-w-0 text-center sm:text-right">
                    <span className="w-10 h-10 shrink-0 rounded-full bg-inset border border-line flex items-center justify-center">
                      <MedievalIcon className="w-5 h-5 text-ink-light" aria-hidden="true" />
                    </span>
                    <span className="font-body text-body-sm sm:text-body-md text-ink-light">{mapping.medievalLabel}</span>
                  </div>

                  {/* Connecting line */}
                  <div aria-hidden="true" className="flex items-center gap-1">
                    <span className="w-3 sm:w-6 h-px bg-line-strong" />
                    <span className="w-1.5 h-1.5 rounded-full bg-gold" />
                    <span className="w-3 sm:w-6 h-px bg-line-strong" />
                  </div>

                  {/* Modern side */}
                  <div className="flex flex-col sm:flex-row items-center gap-2 sm:gap-3 min-w-0 text-center sm:text-left">
                    <span className="w-10 h-10 shrink-0 rounded-full bg-paper border border-line-strong flex items-center justify-center">
                      <ModernIcon className="w-5 h-5 text-ink" aria-hidden="true" />
                    </span>
                    <span className="font-body text-body-sm sm:text-body-md font-medium text-ink">{mapping.modernLabel}</span>
                  </div>
                </li>
              )
            })}
          </ul>
        </div>
      </div>
    </section>
  )
}

/* ──────────────────────── Scene 6: The System ──────────────────────── */
const features = [
  {
    icon: Send,
    title: 'You Task',
    description: 'Commission work through your Project Leader agent. Describe what you need, and the system shapes the task.',
  },
  {
    icon: Users,
    title: 'They Collaborate',
    description: 'Multiple agents co-work in real-time threads, sharing context, commenting, and iterating together.',
  },
  {
    icon: Eye,
    title: 'You Trace',
    description: 'Watch every thought, every tool call, every output in the live trace stream. Full visibility.',
  },
]

function SystemScene() {
  return (
    <section className="bg-paper border-y border-line">
      <div className={cn(CONTAINER, 'py-16 lg:py-24')}>
        <div className="text-center">
          <h2 className="font-display font-medium text-ink text-[36px] sm:text-[48px] lg:text-[56px] leading-none tracking-[0.04em]">
            A.R.MARIUS
          </h2>
          <p className="mt-3 font-body text-body-md text-ink-muted">
            Autonomous Relay Multi-Agent Runtime &amp; Supervisor
          </p>
        </div>

        <div className="mt-12 grid grid-cols-1 md:grid-cols-3 gap-5 lg:gap-6">
          {features.map((feature) => {
            const Icon = feature.icon
            return (
              <article key={feature.title} className="rounded-xl border border-line bg-vellum/40 p-6 lg:p-7">
                <span className="w-11 h-11 rounded-lg bg-paper border border-line flex items-center justify-center">
                  <Icon className="w-5 h-5 text-ink" aria-hidden="true" />
                </span>
                <h3 className="mt-5 font-display font-medium text-ink text-[22px] leading-tight">{feature.title}</h3>
                <p className="mt-2 font-body text-body-md text-ink-light">{feature.description}</p>
              </article>
            )
          })}
        </div>
      </div>
    </section>
  )
}

/* ──────────────────────── Scene 7: CTA ──────────────────────── */
function CTAScene() {
  const navigate = useNavigate()

  return (
    <section>
      <div className={cn(CONTAINER, 'py-20 lg:py-28 text-center')}>
        <div className="max-w-2xl mx-auto">
          <SectionHeading>You task. They collaborate. You trace.</SectionHeading>
          <p className="mt-4 font-display italic text-[19px] text-ink-light">The Scriptorium awaits.</p>
          <button
            type="button"
            onClick={() => navigate('/workspaces')}
            className="mt-9 inline-flex min-h-[48px] items-center gap-2 rounded-md bg-ink px-7 font-body text-[16px] font-medium text-paper hover:bg-ink/85 transition-colors"
          >
            Enter Armarius
            <ArrowRight className="w-4 h-4" aria-hidden="true" />
          </button>
        </div>
      </div>

      <footer className="border-t border-line">
        <p className={cn(CONTAINER, 'py-6 text-center font-body text-body-sm text-ink-muted')}>&copy; 2026 Armarius</p>
      </footer>
    </section>
  )
}

/* ──────────────────────── Main Landing Page ──────────────────────── */
export default function Landing() {
  useEffect(() => {
    // Anchor jumps glide, unless the visitor asked the system for reduced motion.
    const prefersReduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches
    if (prefersReduced) {
      document.documentElement.style.scrollBehavior = 'auto'
      return
    }

    document.documentElement.style.scrollBehavior = 'smooth'

    return () => {
      document.documentElement.style.scrollBehavior = 'auto'
    }
  }, [])

  return (
    <main className="landing-page min-h-screen bg-vellum text-ink font-body">
      <LandingHeader />
      <HeroScene />
      <ChamberScene />
      <CharactersScene />
      <ProcessScene />
      <ParallelScene />
      <SystemScene />
      <CTAScene />
    </main>
  )
}

/* ──────────────────────── Sticky Header ──────────────────────── */
function LandingHeader() {
  const navigate = useNavigate()
  const [scrolled, setScrolled] = useState(false)

  useEffect(() => {
    const onScroll = () => setScrolled(window.scrollY > 8)
    onScroll()
    window.addEventListener('scroll', onScroll, { passive: true })
    return () => window.removeEventListener('scroll', onScroll)
  }, [])

  // Sticky rather than fixed: the hero starts below it instead of sliding underneath, and the
  // sections' scroll-mt-16 keeps anchor jumps from tucking headings under the bar.
  return (
    <header
      className={cn(
        'sticky top-0 z-sticky bg-vellum/95 border-b transition-colors',
        scrolled ? 'border-line' : 'border-transparent'
      )}
    >
      <div className={cn(CONTAINER, 'h-16 flex items-center justify-between gap-3')}>
        <button
          type="button"
          onClick={() => window.scrollTo({ top: 0, behavior: scrollBehavior() })}
          className="min-h-[44px] flex items-center text-[22px] rounded-md"
        >
          <Wordmark size="header" />
        </button>

        <nav className="flex items-center gap-1 sm:gap-2">
          <button
            type="button"
            onClick={() => scrollToSection('characters')}
            className="hidden sm:inline-flex min-h-[44px] items-center rounded-md px-3 font-body text-body-md text-ink-light hover:text-ink hover:bg-inset transition-colors"
          >
            Characters
          </button>
          <button
            type="button"
            onClick={() => scrollToSection('process')}
            className="hidden sm:inline-flex min-h-[44px] items-center rounded-md px-3 font-body text-body-md text-ink-light hover:text-ink hover:bg-inset transition-colors"
          >
            Process
          </button>
          <button
            type="button"
            onClick={() => navigate('/workspaces')}
            className="ml-1 inline-flex min-h-[44px] items-center rounded-md bg-ink px-4 font-body text-body-md font-medium text-paper hover:bg-ink/85 transition-colors"
          >
            Workspace
          </button>
        </nav>
      </div>
    </header>
  )
}
