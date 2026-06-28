import { useEffect, useRef, useLayoutEffect, useState } from 'react'
import { useNavigate } from 'react-router'
import gsap from 'gsap'
import { ScrollTrigger } from 'gsap/ScrollTrigger'
import { motion } from 'framer-motion'
import {
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

gsap.registerPlugin(ScrollTrigger)

/* ──────────────────────── Scene 1: Hero ──────────────────────── */
function HeroScene() {
  const sectionRef = useRef<HTMLDivElement>(null)
  const titleRef = useRef<HTMLHeadingElement>(null)
  const subtitleRef = useRef<HTMLParagraphElement>(null)
  const dropcapRef = useRef<HTMLSpanElement>(null)
  const scrollIndicatorRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    const prefersReduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches
    if (prefersReduced) {
      gsap.set([dropcapRef.current, titleRef.current, subtitleRef.current, scrollIndicatorRef.current], {
        opacity: 1,
        y: 0,
      })
      return
    }

    const tl = gsap.timeline({ delay: 0.3 })

    tl.fromTo(
      dropcapRef.current,
      { opacity: 0, scale: 0.5 },
      { opacity: 1, scale: 1, duration: 1, ease: 'power3.out' }
    )

    if (titleRef.current) {
      const letters = titleRef.current.querySelectorAll('.hero-letter')
      tl.fromTo(
        letters,
        { opacity: 0, y: 30 },
        { opacity: 1, y: 0, duration: 0.6, stagger: 0.05, ease: 'power2.out' },
        '-=0.5'
      )
    }

    tl.fromTo(
      subtitleRef.current,
      { opacity: 0, y: 20 },
      { opacity: 1, y: 0, duration: 0.8, ease: 'power2.out' },
      '-=0.2'
    )

    tl.fromTo(
      scrollIndicatorRef.current,
      { opacity: 0 },
      { opacity: 1, duration: 0.6, ease: 'power2.out' },
      '-=0.3'
    )

    return () => { tl.kill() }
  }, [])

  const titleText = 'Armarius'

  return (
    <section
      ref={sectionRef}
      className="relative min-h-screen flex items-center justify-center overflow-hidden"
      style={{
        backgroundImage: 'url(/hero-scriptorium.jpg)',
        backgroundSize: 'cover',
        backgroundPosition: 'center',
      }}
    >
      {/* Dark overlay */}
      <div className="absolute inset-0 bg-black/[0.60]" />

      <div className="relative z-10 text-center px-4">
        {/* Title: illuminated "A" + "rmarius" */}
        <h1
          ref={titleRef}
          className="font-bold text-white mt-2 inline-block"
          style={{
            fontFamily: "'Cinzel Decorative', 'Cinzel', Georgia, serif",
            fontSize: 'clamp(56px, 8vw, 96px)',
            letterSpacing: '0.06em',
            lineHeight: 1.0,
            textShadow: '0 0 30px rgba(212,168,67,0.3), 0 2px 10px rgba(0,0,0,0.5)',
          }}
        >
          {/* "A" — illuminated gold */}
          <span
            ref={dropcapRef}
            className="inline-block opacity-0"
            style={{
              fontFamily: "'Cinzel Decorative', 'Cinzel', Georgia, serif",
              color: '#D4A843',
              fontSize: '1.1em',
              textShadow: '0 0 20px rgba(212,168,67,0.5), 0 0 60px rgba(212,168,67,0.2), 2px 2px 4px rgba(0,0,0,0.3)',
            }}
          >
            A
          </span>
          {/* "rmarius" — letter-by-letter reveal */}
          {titleText.slice(1).split('').map((letter, i) => (
            <span key={i} className="hero-letter inline-block opacity-0">
              {letter}
            </span>
          ))}
        </h1>

        {/* Subtitle */}
        <p
          ref={subtitleRef}
          className="text-gold-light mt-5 opacity-0"
          style={{
            fontFamily: "'Cinzel', Georgia, serif",
            fontSize: 'clamp(13px, 1.6vw, 16px)',
            fontWeight: 400,
            letterSpacing: '0.15em',
            textTransform: 'uppercase' as const,
          }}
        >
          From medieval manuscripts to digital collaboration
        </p>
      </div>

      {/* Scroll indicator */}
      <div
        ref={scrollIndicatorRef}
        className="absolute bottom-8 left-1/2 -translate-x-1/2 flex flex-col items-center gap-2 opacity-0"
      >
        <span className="text-gold-light text-sm" style={{ fontFamily: "'Cinzel', serif", letterSpacing: '0.08em' }}>Scroll to begin</span>
        <motion.div
          animate={{ y: [0, 8, 0] }}
          transition={{ duration: 1.5, repeat: Infinity, ease: 'easeInOut' }}
        >
          <ChevronDown className="w-6 h-6 text-gold-light" />
        </motion.div>
      </div>
    </section>
  )
}

/* ──────────────────────── Scene 2: The Chamber (PINNED) ──────────────────────── */
function ChamberScene() {
  const sectionRef = useRef<HTMLDivElement>(null)
  const text1Ref = useRef<HTMLDivElement>(null)
  const text2Ref = useRef<HTMLDivElement>(null)
  const text3Ref = useRef<HTMLDivElement>(null)
  const line1Ref = useRef<HTMLDivElement>(null)
  const line2Ref = useRef<HTMLDivElement>(null)

  useLayoutEffect(() => {
    const section = sectionRef.current
    if (!section) return

    const prefersReduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches
    if (prefersReduced) {
      gsap.set([text1Ref.current, text2Ref.current, text3Ref.current], { opacity: 1, y: 0 })
      return
    }

    const ctx = gsap.context(() => {
      const scrollTl = gsap.timeline({
        scrollTrigger: {
          trigger: section,
          start: 'top top',
          end: '+=300%',
          pin: true,
          scrub: 0.6,
        },
      })

      // Text 1: in then out
      scrollTl.fromTo(text1Ref.current, { opacity: 0, y: 50 }, { opacity: 1, y: 0, duration: 0.15 }, 0)
      scrollTl.to(text1Ref.current, { opacity: 0, y: -50, duration: 0.08 }, 0.22)

      // Line 1
      scrollTl.fromTo(line1Ref.current, { scaleX: 0 }, { scaleX: 1, duration: 0.06 }, 0.18)
      scrollTl.to(line1Ref.current, { opacity: 0, duration: 0.04 }, 0.26)

      // Text 2: in then out
      scrollTl.fromTo(text2Ref.current, { opacity: 0, y: 50 }, { opacity: 1, y: 0, duration: 0.15 }, 0.30)
      scrollTl.to(text2Ref.current, { opacity: 0, y: -50, duration: 0.08 }, 0.52)

      // Line 2
      scrollTl.fromTo(line2Ref.current, { scaleX: 0 }, { scaleX: 1, duration: 0.06 }, 0.48)
      scrollTl.to(line2Ref.current, { opacity: 0, duration: 0.04 }, 0.56)

      // Text 3: in and stays
      scrollTl.fromTo(text3Ref.current, { opacity: 0, y: 50 }, { opacity: 1, y: 0, duration: 0.15 }, 0.60)
      scrollTl.to({}, { duration: 0.25 }) // hold

    }, section)

    return () => ctx.revert()
  }, [])

  return (
    <section
      ref={sectionRef}
      id="chamber"
      className="relative min-h-screen flex items-center justify-center overflow-hidden"
      style={{
        backgroundImage: 'url(/step-prepare.jpg)',
        backgroundSize: 'cover',
        backgroundPosition: 'center',
      }}
    >
      <div className="absolute inset-0 bg-black/[0.55]" />

      <div className="relative z-10 w-full max-w-[800px] mx-auto px-6 text-center">
        {/* Text Block 1 */}
        <div ref={text1Ref} className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 w-full px-6 opacity-0">
          <p style={{ fontFamily: "'Cinzel', Georgia, serif", fontSize: 'clamp(16px, 2vw, 22px)', fontWeight: 400, letterSpacing: '0.02em', lineHeight: 1.6, color: '#fff', textWrap: 'balance' }}>
            The Scriptorium was the heart of every great monastery — a silent workshop where knowledge was preserved by hand, word by word, page by page.
          </p>
        </div>

        {/* Gold line separator 1 */}
        <div
          ref={line1Ref}
          className="absolute top-1/2 left-1/2 -translate-x-1/2 w-24 h-px bg-gold origin-center"
          style={{ marginTop: '80px' }}
        />

        {/* Text Block 2 */}
        <div ref={text2Ref} className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 w-full px-6 opacity-0">
          <p style={{ fontFamily: "'Cinzel', Georgia, serif", fontSize: 'clamp(16px, 2vw, 22px)', fontWeight: 400, letterSpacing: '0.02em', lineHeight: 1.6, color: '#fff', textWrap: 'balance' }}>
            Inside, the Patron prepared vellum and ink; scribes wrote with precision, illuminators brought gold and colour — each a master of their craft, working as one.
          </p>
        </div>

        {/* Gold line separator 2 */}
        <div
          ref={line2Ref}
          className="absolute top-1/2 left-1/2 -translate-x-1/2 w-24 h-px bg-gold origin-center"
          style={{ marginTop: '80px' }}
        />

        {/* Text Block 3 */}
        <div ref={text3Ref} className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 w-full px-6 opacity-0">
          <p style={{ fontFamily: "'Cinzel', Georgia, serif", fontSize: 'clamp(16px, 2vw, 22px)', fontWeight: 400, letterSpacing: '0.02em', lineHeight: 1.6, color: '#fff', textWrap: 'balance' }}>
            That same spirit lives on today — not in stone corridors, but in code. Armarius carries the Scriptorium into the age of AI.
          </p>
        </div>
      </div>
    </section>
  )
}

/* ──────────────────────── Scene 3: The Characters (CENTERED) ──────────────────────── */
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
  const sectionRef = useRef<HTMLDivElement>(null)
  const cardsRef = useRef<(HTMLDivElement | null)[]>([])

  useLayoutEffect(() => {
    const section = sectionRef.current
    if (!section) return

    const prefersReduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches
    if (prefersReduced) {
      cardsRef.current.forEach(c => { if (c) gsap.set(c, { opacity: 1, y: 0 }) })
      return
    }

    const ctx = gsap.context(() => {
      cardsRef.current.forEach((card, i) => {
        if (!card) return
        gsap.fromTo(
          card,
          { opacity: 0, y: 60 },
          {
            opacity: 1,
            y: 0,
            duration: 0.8,
            ease: 'power2.out',
            scrollTrigger: {
              trigger: card,
              start: 'top 85%',
              toggleActions: 'play none none none',
            },
            delay: i * 0.15,
          }
        )
      })
    }, section)

    return () => ctx.revert()
  }, [])

  return (
    <section ref={sectionRef} id="characters" className="relative min-h-screen bg-vellum-deep flex flex-col items-center justify-center py-20 px-6">
      {/* Title */}
      <div className="text-center mb-12">
        <h2
          className="font-semibold text-ink"
          style={{
            fontFamily: "'Cinzel', Georgia, serif",
            fontSize: 'clamp(32px, 4.5vw, 48px)',
            letterSpacing: '0.06em',
          }}
        >
          The Characters
        </h2>
      </div>

      {/* 3 Cards - Centered Grid */}
      <div className="flex flex-col md:flex-row items-center justify-center gap-10 max-w-5xl w-full">
        {characters.map((char, i) => (
          <div
            key={i}
            ref={(el) => { cardsRef.current[i] = el }}
            className="flex flex-col items-center text-center opacity-0 h-[480px]"
            style={{ width: 'clamp(260px, 28vw, 320px)', flex: '0 0 auto' }}
          >
            <div
              className="w-full overflow-hidden rounded-lg border border-vellum-dark shadow-lg flex-shrink-0"
              style={{ height: '320px', minHeight: '320px' }}
            >
              <img
                src={char.image}
                alt={char.name}
                className="w-full h-full object-cover"
                loading="lazy"
                style={{ objectPosition: 'top center' }}
              />
            </div>
            <h3
              className="font-semibold text-ink mt-5"
              style={{ fontFamily: "'Cinzel', Georgia, serif", fontSize: '20px', letterSpacing: '0.02em' }}
            >
              {char.name}
            </h3>
            <p style={{ fontFamily: "'Inter', system-ui, sans-serif", fontSize: '14px', lineHeight: 1.6, color: '#6B5E4E', marginTop: '6px' }}>
              {char.description}
            </p>
          </div>
        ))}
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
  const sectionRef = useRef<HTMLDivElement>(null)
  const stepRefs = useRef<(HTMLDivElement | null)[]>([])

  useLayoutEffect(() => {
    const section = sectionRef.current
    if (!section) return

    const prefersReduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches

    const ctx = gsap.context(() => {
      stepRefs.current.forEach((step, i) => {
        if (!step) return
        const fromX = prefersReduced ? 0 : i % 2 === 0 ? -60 : 60

        if (prefersReduced) {
          gsap.set(step, { opacity: 1, x: 0 })
          return
        }

        gsap.fromTo(
          step,
          { opacity: 0, x: fromX },
          {
            opacity: 1,
            x: 0,
            duration: 0.8,
            ease: 'power2.out',
            scrollTrigger: {
              trigger: step,
              start: 'top 80%',
              end: 'top 50%',
              scrub: true,
            },
          }
        )
      })
    }, section)

    return () => ctx.revert()
  }, [])

  return (
    <section ref={sectionRef} id="process" className="relative bg-vellum py-20 overflow-hidden">
      {/* Title */}
      <div className="text-center mb-16 px-6">
        <h2
          className="font-semibold text-ink"
          style={{
            fontFamily: "'Cinzel', Georgia, serif",
            fontSize: 'clamp(32px, 4.5vw, 48px)',
            letterSpacing: '0.06em',
          }}
        >
          The Process of Creation
        </h2>
      </div>

      {/* Timeline */}
      <div className="relative max-w-5xl mx-auto px-6">
        {/* Center line */}
        <div className="absolute left-1/2 top-0 bottom-0 w-px bg-gold -translate-x-1/2 hidden md:block" />

        {processSteps.map((step, i) => {
          const isEven = i % 2 === 0
          return (
            <div
              key={i}
              ref={(el) => { stepRefs.current[i] = el }}
              className={`relative flex flex-col md:flex-row items-center gap-8 mb-20 last:mb-0 ${
                isEven ? 'md:flex-row' : 'md:flex-row-reverse'
              }`}
            >
              {/* Content side */}
              <div className={`flex-1 ${isEven ? 'md:text-right' : 'md:text-left'}`}>
                <span
                  style={{
                    fontFamily: "'Cinzel', Georgia, serif",
                    fontSize: 'clamp(48px, 6vw, 72px)',
                    fontWeight: 700,
                    lineHeight: 1,
                    color: '#D4A843',
                  }}
                >
                  {step.number}
                </span>
                <h3
                  className="font-semibold text-ink mt-2"
                  style={{ fontFamily: "'Cinzel', Georgia, serif", fontSize: '22px', letterSpacing: '0.02em' }}
                >
                  {step.title}
                </h3>
                <p style={{ fontFamily: "'Inter', system-ui, sans-serif", fontSize: '15px', color: '#6B5E4E', fontStyle: 'italic', marginTop: '6px' }}>
                  &ldquo;{step.medieval}&rdquo;
                </p>
                <div className="flex items-center gap-2 mt-3 justify-center md:justify-start" style={{ flexDirection: isEven ? 'row-reverse' : 'row' }}>
                  <span className="text-gold text-lg">&#8594;</span>
                  <p style={{ fontFamily: "'Inter', system-ui, sans-serif", fontSize: '14px', color: '#2A2318' }}>
                    {step.modern}
                  </p>
                </div>
              </div>

              {/* Center dot */}
              <div className="hidden md:flex w-4 h-4 rounded-full bg-gold border-4 border-vellum flex-shrink-0 z-10" />

              {/* Image side */}
              <div className="flex-1 flex justify-center">
                {step.image ? (
                  <div className="w-full max-w-[300px] overflow-hidden rounded-lg border border-vellum-dark">
                    <img
                      src={step.image}
                      alt={step.title}
                      className="w-full h-auto object-cover"
                      style={{ aspectRatio: '4/3' }}
                      loading="lazy"
                    />
                  </div>
                ) : (
                  <div className="w-full max-w-[300px] h-[180px] rounded-lg border border-dashed border-vellum-dark flex items-center justify-center bg-vellum-deep">
                    <span className="font-semibold text-ink-muted text-lg" style={{ fontFamily: "'Cinzel', serif" }}>{step.title}</span>
                  </div>
                )}
              </div>
            </div>
          )
        })}
      </div>
    </section>
  )
}

/* ──────────────────────── Scene 5: The Parallel (PINNED) ──────────────────────── */
const parallelMappings = [
  { medievalIcon: Feather, medievalLabel: 'Vellum & Quill', modernLabel: 'Code Editor', modernIcon: Monitor },
  { medievalIcon: FlaskConical, medievalLabel: 'Ink & Gold Leaf', modernLabel: 'Data & Context', modernIcon: Database },
  { medievalIcon: Scroll, medievalLabel: 'Manuscript Pages', modernLabel: 'Task Artifacts', modernIcon: FileText },
  { medievalIcon: CandlestickChart, medievalLabel: 'Candlelight', modernLabel: 'Live Trace Stream', modernIcon: Zap },
]

function ParallelScene() {
  const sectionRef = useRef<HTMLDivElement>(null)
  const titleRef = useRef<HTMLHeadingElement>(null)
  const rowRefs = useRef<(HTMLDivElement | null)[]>([])

  useLayoutEffect(() => {
    const section = sectionRef.current
    if (!section) return

    const prefersReduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches
    if (prefersReduced) {
      gsap.set([titleRef.current, ...rowRefs.current], { opacity: 1, y: 0 })
      return
    }

    const ctx = gsap.context(() => {
      const scrollTl = gsap.timeline({
        scrollTrigger: {
          trigger: section,
          start: 'top top',
          end: '+=300%',
          pin: true,
          scrub: 0.6,
        },
      })

      // Title fades in
      scrollTl.fromTo(titleRef.current, { opacity: 0, y: 30 }, { opacity: 1, y: 0, duration: 0.12 }, 0.02)

      // Rows appear sequentially
      rowRefs.current.forEach((row, i) => {
        if (!row) return
        const start = 0.12 + i * 0.18
        scrollTl.fromTo(row, { opacity: 0, y: 40 }, { opacity: 1, y: 0, duration: 0.14 }, start)
      })

      // Hold at the end
      scrollTl.to({}, { duration: 0.1 })

    }, section)

    return () => ctx.revert()
  }, [])

  return (
    <section
      ref={sectionRef}
      className="relative min-h-screen flex flex-col items-center justify-center overflow-hidden"
      style={{
        backgroundImage: 'url(/parallel-split.jpg)',
        backgroundSize: 'cover',
        backgroundPosition: 'center',
      }}
    >
      <div className="absolute inset-0 bg-black/[0.60]" />

      <div className="relative z-10 w-full max-w-3xl mx-auto px-6 text-center">
        <h2
          ref={titleRef}
          className="font-bold text-gold-light mb-16 opacity-0"
          style={{ fontFamily: "'Cinzel', Georgia, serif", fontSize: 'clamp(32px, 5vw, 48px)', letterSpacing: '0.04em' }}
        >
          Then and Now
        </h2>

        <div className="flex flex-col gap-10">
          {parallelMappings.map((mapping, i) => {
            const MedievalIcon = mapping.medievalIcon
            const ModernIcon = mapping.modernIcon
            return (
              <div
                key={i}
                ref={(el) => { rowRefs.current[i] = el }}
                className="flex items-center justify-center gap-4 md:gap-8 opacity-0"
              >
                {/* Medieval side */}
                <div className="flex items-center gap-3 flex-1 justify-end">
                  <span className="hidden sm:inline text-white" style={{ fontFamily: "'Inter', system-ui, sans-serif", fontSize: '15px', fontWeight: 500 }}>
                    {mapping.medievalLabel}
                  </span>
                  <div className="w-12 h-12 rounded-full bg-vellum/10 border border-gold/40 flex items-center justify-center flex-shrink-0">
                    <MedievalIcon className="w-5 h-5 text-gold" />
                  </div>
                </div>

                {/* Connecting line */}
                <div className="flex items-center gap-1 flex-shrink-0">
                  <div className="w-6 md:w-12 h-px bg-gold/60" />
                  <div className="w-2 h-2 rounded-full bg-gold" />
                  <div className="w-6 md:w-12 h-px bg-gold/60" />
                </div>

                {/* Modern side */}
                <div className="flex items-center gap-3 flex-1 justify-start">
                  <div className="w-12 h-12 rounded-full bg-vellum/10 border border-gold/40 flex items-center justify-center flex-shrink-0">
                    <ModernIcon className="w-5 h-5 text-gold-light" />
                  </div>
                  <span className="hidden sm:inline text-gold-light" style={{ fontFamily: "'Inter', system-ui, sans-serif", fontSize: '15px', fontWeight: 500 }}>
                    {mapping.modernLabel}
                  </span>
                </div>
              </div>
            )
          })}
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
    accent: '#C25E3A',
  },
  {
    icon: Users,
    title: 'They Collaborate',
    description: 'Multiple agents co-work in real-time threads, sharing context, commenting, and iterating together.',
    accent: '#D4A843',
  },
  {
    icon: Eye,
    title: 'You Trace',
    description: 'Watch every thought, every tool call, every output in the live trace stream. Full visibility.',
    accent: '#4A9E6B',
  },
]

function SystemScene() {
  const sectionRef = useRef<HTMLDivElement>(null)
  const cardRefs = useRef<(HTMLDivElement | null)[]>([])

  useLayoutEffect(() => {
    const section = sectionRef.current
    if (!section) return

    const prefersReduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches

    const ctx = gsap.context(() => {
      cardRefs.current.forEach((card, i) => {
        if (!card) return
        if (prefersReduced) {
          gsap.set(card, { opacity: 1, y: 0 })
          return
        }

        gsap.fromTo(
          card,
          { opacity: 0, y: 50 },
          {
            opacity: 1,
            y: 0,
            duration: 0.7,
            ease: 'power2.out',
            scrollTrigger: {
              trigger: card,
              start: 'top 85%',
              toggleActions: 'play none none none',
            },
            delay: i * 0.15,
          }
        )
      })
    }, section)

    return () => ctx.revert()
  }, [])

  // CSS parchment texture as data URI — seamless warm parchment background
  const parchmentBg = `url("data:image/svg+xml,%3Csvg width='200' height='200' xmlns='http://www.w3.org/2000/svg'%3E%3Cfilter id='noise'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='0.65' numOctaves='3' stitchTiles='stitch'/%3E%3C/filter%3E%3Crect width='100%25' height='100%25' filter='url(%23noise)' opacity='0.06'/%3E%3C/svg%3E")`

  return (
    <section ref={sectionRef} className="relative py-24 px-6" style={{ backgroundColor: '#1A1410' }}>
      <div className="max-w-6xl mx-auto">
        {/* Title */}
        <div className="text-center mb-6">
          <h2
            style={{
              fontFamily: "'Cinzel Decorative', 'Cinzel', Georgia, serif",
              fontSize: 'clamp(36px, 6vw, 64px)',
              fontWeight: 700,
              color: '#D4A843',
              letterSpacing: '0.08em',
              textShadow: '0 0 30px rgba(212,168,67,0.2)',
            }}
          >
            A.R.MARIUS
          </h2>
          <p style={{ fontFamily: "'Inter', system-ui, sans-serif", fontSize: '13px', color: 'rgba(212,168,67,0.6)', letterSpacing: '0.06em', marginTop: '10px' }}>
            Autonomous Relay Multi-Agent Runtime &amp; Supervisor
          </p>
        </div>

        {/* Feature Cards */}
        <div className="grid grid-cols-1 md:grid-cols-3 gap-6 mt-16">
          {features.map((feature, i) => {
            const Icon = feature.icon
            return (
              <div
                key={i}
                ref={(el) => { cardRefs.current[i] = el }}
                className="group relative rounded-lg p-8 transition-all duration-300 hover:-translate-y-1 cursor-default opacity-0 overflow-hidden"
                style={{
                  backgroundColor: '#F0E6D0',
                  backgroundImage: parchmentBg,
                  boxShadow: '0 4px 20px rgba(0,0,0,0.3), inset 0 0 60px rgba(194,94,58,0.08)',
                }}
                onMouseEnter={(e) => {
                  ;(e.currentTarget as HTMLDivElement).style.boxShadow = `0 8px 32px rgba(0,0,0,0.4), 0 0 20px ${feature.accent}25, inset 0 0 60px rgba(194,94,58,0.12)`
                }}
                onMouseLeave={(e) => {
                  ;(e.currentTarget as HTMLDivElement).style.boxShadow = '0 4px 20px rgba(0,0,0,0.3), inset 0 0 60px rgba(194,94,58,0.08)'
                }}
              >
                {/* Subtle edge effect */}
                <div
                  className="absolute inset-0 rounded-lg pointer-events-none"
                  style={{
                    boxShadow: 'inset 0 0 0 1px rgba(139,119,90,0.2), inset 0 0 30px rgba(194,94,58,0.05)',
                  }}
                />

                {/* Content */}
                <div className="relative z-10">
                  {/* Icon + Accent bar */}
                  <div className="flex items-center gap-3 mb-5">
                    <div
                      className="w-10 h-10 rounded-full flex items-center justify-center flex-shrink-0"
                      style={{ backgroundColor: `${feature.accent}15`, border: `1px solid ${feature.accent}40` }}
                    >
                      <Icon className="w-5 h-5" style={{ color: feature.accent }} />
                    </div>
                    <div className="w-12 h-1 rounded-full" style={{ backgroundColor: feature.accent, opacity: 0.5 }} />
                  </div>

                  <h3
                    style={{
                      fontFamily: "'Caveat', 'Cinzel', cursive",
                      fontSize: '38px',
                      fontWeight: 700,
                      lineHeight: 1.1,
                      color: '#2A2318',
                    }}
                  >
                    {feature.title}
                  </h3>
                  <p
                    style={{
                      fontFamily: "'Inter', system-ui, sans-serif",
                      fontSize: '14px',
                      lineHeight: 1.6,
                      color: '#5A4E3E',
                      marginTop: '10px',
                    }}
                  >
                    {feature.description}
                  </p>
                </div>
              </div>
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
    <section
      className="relative min-h-screen flex flex-col items-center justify-center overflow-hidden"
      style={{
        backgroundImage: 'url(/hero-scriptorium.jpg)',
        backgroundSize: 'cover',
        backgroundPosition: 'center',
      }}
    >
      {/* Gradient overlay: dark at edges */}
      <div
        className="absolute inset-0"
        style={{
          background: 'radial-gradient(ellipse at center, rgba(26,20,16,0.70) 0%, rgba(26,20,16,0.90) 100%)',
        }}
      />

      <div className="relative z-10 text-center px-6 max-w-2xl mx-auto">
        <h2
          className="font-bold text-white"
          style={{
            fontFamily: "'Cinzel', Georgia, serif",
            fontSize: 'clamp(28px, 5vw, 48px)',
            lineHeight: 1.2,
            letterSpacing: '0.02em',
          }}
        >
          You task. They collaborate. You trace.
        </h2>
        <p style={{ fontFamily: "'Cinzel', Georgia, serif", fontSize: '16px', color: '#E8C96A', letterSpacing: '0.08em', marginTop: '20px' }}>
          The Scriptorium awaits.
        </p>

        <motion.button
          onClick={() => navigate('/workspaces')}
          className="mt-10 font-semibold text-white rounded-lg inline-block cursor-pointer"
          style={{
            backgroundColor: '#C25E3A',
            padding: '16px 48px',
            fontSize: '18px',
            fontFamily: "'Cinzel', Georgia, serif",
            letterSpacing: '0.04em',
          }}
          whileHover={{
            scale: 1.05,
            boxShadow: '0 8px 32px rgba(212,168,67,0.4)',
          }}
          whileTap={{ scale: 0.98 }}
          transition={{ type: 'spring', stiffness: 400, damping: 17 }}
        >
          Enter Armarius
        </motion.button>
      </div>

      {/* Footer */}
      <div className="absolute bottom-6 left-0 right-0 text-center">
        <p style={{ fontFamily: "'Inter', system-ui, sans-serif", fontSize: '12px', color: '#A89880', letterSpacing: '0.04em' }}>
          &copy; 2026 Armarius
        </p>
      </div>
    </section>
  )
}

/* ──────────────────────── Main Landing Page ──────────────────────── */
export default function Landing() {
  useEffect(() => {
    // Check for reduced motion preference
    const prefersReduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches
    if (prefersReduced) {
      document.documentElement.style.scrollBehavior = 'auto'
      return
    }

    // Smooth scroll via CSS
    document.documentElement.style.scrollBehavior = 'smooth'

    return () => {
      document.documentElement.style.scrollBehavior = 'auto'
    }
  }, [])

  // Cleanup all ScrollTriggers on unmount
  useEffect(() => {
    return () => {
      ScrollTrigger.getAll().forEach((st: any) => st.kill())
    }
  }, [])

  return (
    <main className="landing-page">
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
    const onScroll = () => setScrolled(window.scrollY > 60)
    window.addEventListener('scroll', onScroll, { passive: true })
    return () => window.removeEventListener('scroll', onScroll)
  }, [])

  const scrollToSection = (id: string) => {
    const el = document.getElementById(id)
    if (el) {
      el.scrollIntoView({ behavior: 'smooth' })
    }
  }

  return (
    <header
      className="fixed top-0 left-0 right-0 z-50 transition-all duration-500"
      style={{
        backgroundColor: scrolled ? 'rgba(26,20,16,0.85)' : 'transparent',
        backdropFilter: scrolled ? 'blur(12px)' : 'none',
        borderBottom: scrolled ? '1px solid rgba(212,168,67,0.15)' : '1px solid transparent',
      }}
    >
      <div className="max-w-7xl mx-auto px-6 h-14 flex items-center justify-between">
        {/* Brand */}
        <button
          onClick={() => window.scrollTo({ top: 0, behavior: 'smooth' })}
          className="text-gold hover:text-gold-light transition-colors"
          style={{ fontFamily: "'Cinzel Decorative', 'Cinzel', serif", fontSize: '20px', letterSpacing: '0.04em' }}
        >
          Armarius
        </button>

        {/* Nav */}
        <nav className="flex items-center gap-5">
          <button
            onClick={() => scrollToSection('characters')}
            className="hidden sm:block text-sm text-[#A89880] hover:text-gold transition-colors"
            style={{ fontFamily: "'Cinzel', serif", letterSpacing: '0.04em' }}
          >
            Characters
          </button>
          <button
            onClick={() => scrollToSection('process')}
            className="hidden sm:block text-sm text-[#A89880] hover:text-gold transition-colors"
            style={{ fontFamily: "'Cinzel', serif", letterSpacing: '0.04em' }}
          >
            Process
          </button>
          <button
            onClick={() => navigate('/workspaces')}
            className="px-4 py-1.5 text-sm font-medium text-white bg-terracotta hover:bg-terracotta-light rounded-md transition-colors"
            style={{ fontFamily: "'Cinzel', serif", letterSpacing: '0.04em' }}
          >
            Workspace
          </button>
        </nav>
      </div>
    </header>
  )
}
