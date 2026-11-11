import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router';
import { useTranslation } from 'react-i18next';
import { motion } from 'framer-motion';
import {
  ArrowDown,
  ArrowRight,
  Binoculars,
  Building2,
  Orbit,
  Sparkle,
  SquareKanban,
  type LucideIcon,
} from 'lucide-react';
import { Brand } from '@/components/Brand';
import ThemeSwitch from '@/components/ThemeSwitch';
import DemoPanel from '@/components/landing/DemoPanel';
import GalaxyScene from '@/components/landing/GalaxyScene';
import { LandingDemo } from '@/components/landing/landingDemo';
import { useTheme } from '@/hooks/use-theme';
import { cn } from '@/lib/utils';
import { useAppStore } from '@/store/appStore';

/*
 * The public front page (Đài quan sát design, "cosmic landing"): four chapters scrolled over
 * one fixed galaxy. The scroll position drives the camera, so reading the page is the journey.
 *
 * Copy is never hidden behind a scroll animation: every chapter is readable as plain text in a
 * preview, a print or a full-page capture; the galaxy only moves behind it.
 */

const CHAPTERS = [
  { id: 'origin', label: 'landing.chapters.origin' },
  { id: 'living-company', label: 'landing.chapters.company' },
  { id: 'working-orbit', label: 'landing.chapters.workflow' },
  { id: 'enter-armarius', label: 'landing.chapters.invitation' },
] as const;

/** Stable across renders: the scene paces its journey by these sections. */
const CHAPTER_IDS = CHAPTERS.map((chapter) => chapter.id);
/** The scripted demo only plays while one of these chapters is on screen. */
const DEMO_CHAPTERS = ['living-company', 'working-orbit'];

function prefersReducedMotion() {
  return window.matchMedia('(prefers-reduced-motion: reduce)').matches;
}

function scrollToChapter(id: string) {
  document.getElementById(id)?.scrollIntoView({ behavior: prefersReducedMotion() ? 'auto' : 'smooth' });
}

const kicker = 'inline-flex items-center gap-2 font-mono text-[9px] uppercase leading-relaxed tracking-[0.15em] text-ink-muted sm:text-[11px]';
const chapterTitle = 'my-[23px] font-display font-normal tracking-[-0.052em] text-ink-strong';
const chapterBody = 'max-w-[590px] font-body text-[14px] leading-[1.75] text-ink-light sm:text-[16px] sm:leading-[1.85]';
const chapterShell =
  'relative mx-auto flex w-full max-w-[1680px] min-h-[108svh] items-end px-[22px] pb-[92px] pt-[100px] md:min-h-[112vh] md:items-center md:px-[55px] md:pb-[100px] md:pt-[130px] lg:px-[clamp(70px,8vw,138px)]';
/** Narrow and portrait screens: the building takes a band above the copy (see GalaxyScene). */
const chapterBand =
  'max-md:pt-[calc(100px+min(61vw,36svh))] md:portrait:items-end md:portrait:pt-[calc(100px+min(61vw,36svh))]';
const chapterCopy = 'relative w-full md:w-[min(650px,68vw)] lg:w-[min(660px,50vw)]';

function Annotation({ kickerText, text, side }: { kickerText: string; text: string; side: 'left' | 'right' }) {
  return (
    <div
      aria-hidden="true"
      className={cn(
        'absolute hidden gap-1.5 font-mono text-[9px] uppercase tracking-[0.12em] text-ink-muted md:landscape:grid',
        side === 'left' ? 'bottom-[19%] left-[10%]' : 'bottom-[22%] right-[10%] text-right'
      )}
    >
      <span>{kickerText}</span>
      <strong className="text-[10px] font-normal normal-case tracking-[0.04em] text-ink-light">{text}</strong>
      <i className={cn('absolute top-[7px] h-px w-[90px] bg-line-strong', side === 'left' ? 'left-[calc(100%+15px)]' : 'right-[calc(100%+15px)]')} />
    </div>
  );
}

function FloorRow({ code, icon: Icon, title, body }: { code: string; icon: LucideIcon; title: string; body: string }) {
  return (
    <div className="grid grid-cols-[28px_27px_1fr] items-center gap-3.5 border-t border-line py-4">
      <span className="font-mono text-[10px] text-ink-muted">{code}</span>
      <Icon className="h-[21px] w-[21px] text-gold" strokeWidth={1.4} aria-hidden />
      <p className="grid gap-1">
        <strong className="font-display text-[18px] font-normal text-ink-strong">{title}</strong>
        <small className="text-[11px] text-ink-light">{body}</small>
      </p>
    </div>
  );
}

export default function Landing() {
  const { t } = useTranslation();
  const [theme] = useTheme();
  const navigate = useNavigate();
  const currentUser = useAppStore((s) => s.currentUser);
  const [activeChapter, setActiveChapter] = useState<string>('origin');
  const dark = theme === 'dark';
  // One scripted demo for the page: the scene and the inbox panel both read it.
  const [demo] = useState(() => new LandingDemo());
  // Without WebGL there is no building, so the chapters keep no band free for it.
  const [sceneLost, setSceneLost] = useState(false);
  const band = sceneLost ? '' : chapterBand;

  // Signed in: straight to the workspaces. Otherwise the sign-in screen first.
  const enter = () => navigate(currentUser ? '/workspaces' : '/login');

  useEffect(() => {
    const observer = new IntersectionObserver(
      (entries) => {
        const visible = entries.filter((entry) => entry.isIntersecting).sort((a, b) => b.intersectionRatio - a.intersectionRatio)[0];
        if (visible) setActiveChapter(visible.target.id);
      },
      { threshold: [0.25, 0.45, 0.65] }
    );
    CHAPTERS.forEach(({ id }) => {
      const element = document.getElementById(id);
      if (element) observer.observe(element);
    });
    return () => observer.disconnect();
  }, []);

  useEffect(() => {
    const onScreen = new Set<string>();
    const sync = () => demo.setRunning(onScreen.size > 0 && !document.hidden);
    const observer = new IntersectionObserver(
      (entries) => {
        entries.forEach((entry) => {
          if (entry.isIntersecting) onScreen.add(entry.target.id);
          else onScreen.delete(entry.target.id);
        });
        sync();
      },
      { threshold: 0.2 }
    );
    DEMO_CHAPTERS.forEach((id) => {
      const element = document.getElementById(id);
      if (element) observer.observe(element);
    });
    document.addEventListener('visibilitychange', sync);
    return () => {
      observer.disconnect();
      document.removeEventListener('visibilitychange', sync);
      demo.setRunning(false);
    };
  }, [demo]);

  return (
    <div className={cn('relative min-h-[100dvh] overflow-x-clip font-body text-ink', dark ? 'bg-canvas-deep' : 'bg-canvas')}>
      <GalaxyScene theme={theme} chapterIds={CHAPTER_IDS} demo={demo} onUnavailable={() => setSceneLost(true)} />
      {/* Veil between galaxy and copy: from the left on wide screens, from below on a phone. */}
      <div
        aria-hidden="true"
        className={cn(
          'pointer-events-none fixed inset-0 z-[1] bg-gradient-to-t md:bg-gradient-to-r',
          dark ? 'from-canvas-deep/80 via-canvas-deep/20 to-transparent' : 'from-canvas/90 via-canvas/25 to-transparent'
        )}
      />

      <header className="fixed inset-x-0 top-0 z-30 flex min-h-[70px] items-center justify-between gap-3 border-b border-line bg-canvas/70 px-4 backdrop-blur-[18px] backdrop-saturate-[1.3] md:min-h-[82px] md:gap-6 md:px-[clamp(24px,4vw,66px)]">
        <button type="button" onClick={() => scrollToChapter('origin')} aria-label={t('landing.nav.home')} className="min-w-0 rounded-md text-left">
          <Brand />
        </button>
        <nav aria-label={t('landing.nav.label')} className="hidden items-center gap-7 lg:flex">
          <button type="button" onClick={() => scrollToChapter('living-company')} className="min-h-[42px] text-[13px] text-ink-light transition-colors hover:text-ink-strong">
            {t('landing.nav.company')}
          </button>
          <button type="button" onClick={() => scrollToChapter('working-orbit')} className="min-h-[42px] text-[13px] text-ink-light transition-colors hover:text-ink-strong">
            {t('landing.nav.workflow')}
          </button>
        </nav>
        <div className="flex shrink-0 items-center gap-2 md:gap-3">
          <ThemeSwitch compact className="md:hidden" />
          <ThemeSwitch className="hidden md:flex" />
          <button type="button" onClick={enter} className="btn btn-primary hidden min-h-[42px] md:inline-flex">
            {t('landing.nav.enter')}
            <ArrowRight className="h-[18px] w-[18px]" aria-hidden />
          </button>
        </div>
      </header>

      <aside aria-label={t('landing.chapters.label')} className="fixed left-6 top-1/2 z-20 hidden -translate-y-1/2 gap-[21px] lg:grid">
        {CHAPTERS.map((chapter, index) => {
          const active = activeChapter === chapter.id;
          return (
            <button
              key={chapter.id}
              type="button"
              onClick={() => scrollToChapter(chapter.id)}
              aria-current={active ? 'step' : undefined}
              className={cn('group grid grid-cols-[20px_28px_auto] items-center gap-2 text-left', active ? 'text-gold' : 'text-ink-muted hover:text-ink-light')}
            >
              <span className="font-mono text-[9px]">0{index + 1}</span>
              <i className={cn('h-px bg-current transition-[width] duration-300 motion-reduce:transition-none', active ? 'w-7' : 'w-3')} />
              <small className="max-w-0 overflow-hidden whitespace-nowrap text-[10px] opacity-0 transition-[max-width,opacity] duration-300 group-hover:max-w-[150px] group-hover:opacity-100 group-focus-visible:max-w-[150px] group-focus-visible:opacity-100 motion-reduce:transition-none">
                {t(chapter.label)}
              </small>
            </button>
          );
        })}
      </aside>

      <main className="relative z-[2]">
        {/* 00 · Origin */}
        <section id="origin" className={chapterShell}>
          <div className={cn(chapterCopy, 'pt-[30vh] md:pt-[4vh]')}>
            <span className={kicker}>
              <Sparkle className="h-4 w-4 fill-current" aria-hidden />
              {t('landing.origin.kicker')}
            </span>
            <h1 className={cn(chapterTitle, 'text-[clamp(44px,13vw,67px)] leading-[0.99] md:text-[clamp(57px,6.5vw,102px)]')}>
              {t('landing.origin.titleA')}
              <br />
              {t('landing.origin.titleB')}
              <br />
              <em className="not-italic text-gold">{t('landing.origin.titleEm')}</em>
            </h1>
            <p className="mb-3 font-display text-[18px] leading-snug text-ink-strong sm:text-[22px]">{t('landing.origin.lede')}</p>
            <p className={chapterBody}>{t('landing.origin.body')}</p>
            <div className="mt-[26px] flex flex-col items-stretch gap-2.5 sm:mt-[34px] sm:flex-row sm:flex-wrap sm:items-center sm:gap-x-6 sm:gap-y-4">
              <button type="button" onClick={enter} className="btn btn-primary min-h-[52px] px-[21px] text-[14px]">
                <Binoculars className="h-5 w-5" aria-hidden />
                {t('landing.origin.cta')}
                <ArrowRight className="h-[19px] w-[19px]" aria-hidden />
              </button>
              <button type="button" onClick={() => scrollToChapter('living-company')} className="group inline-flex min-h-[46px] items-center gap-2 text-[13px] text-ink-light hover:text-ink-strong">
                {t('landing.origin.scroll')}
                <ArrowDown className="h-[18px] w-[18px] transition-transform group-hover:translate-y-[3px] motion-reduce:transition-none" aria-hidden />
              </button>
            </div>
          </div>
          <div
            aria-hidden="true"
            className="absolute bottom-[13%] right-[clamp(35px,6vw,95px)] hidden origin-bottom-right rotate-90 items-center gap-3 font-mono text-[9px] tracking-[0.12em] text-ink-muted md:flex"
          >
            <span>{t('landing.origin.coordinateA')}</span>
            <i className="h-px w-[65px] bg-line-strong" />
            <span>{t('landing.origin.coordinateB')}</span>
          </div>
          <button
            type="button"
            onClick={() => scrollToChapter('living-company')}
            aria-label={t('landing.origin.cueLabel')}
            className="absolute bottom-[27px] left-1/2 flex -translate-x-1/2 items-center gap-3.5 whitespace-nowrap font-mono text-[9px] uppercase tracking-[0.16em] text-ink-muted md:bottom-[38px]"
          >
            <span>{t('landing.origin.cue')}</span>
            <motion.i
              className="grid h-[34px] w-[34px] place-items-center rounded-full border border-line-strong"
              animate={{ y: [0, 6, 0] }}
              transition={{ duration: 2.2, ease: 'easeInOut', repeat: Infinity }}
            >
              <ArrowDown className="h-[15px] w-[15px]" aria-hidden />
            </motion.i>
          </button>
        </section>

        {/* 01 · The living company */}
        <section id="living-company" className={cn(chapterShell, band)}>
          <div className={cn(chapterCopy, 'border-l border-line-strong py-6 pl-5 md:py-9 md:pl-[34px]', dark ? 'bg-gradient-to-r from-canvas-deep/70 to-transparent' : 'bg-gradient-to-r from-canvas/85 to-transparent')}>
            <span className={kicker}>{t('landing.company.kicker')}</span>
            <h2 className={cn(chapterTitle, 'text-[clamp(38px,11vw,56px)] leading-[1.07] md:text-[clamp(43px,4.7vw,70px)]')}>
              {t('landing.company.titleA')}
              <br />
              <em className="not-italic text-gold">{t('landing.company.titleEm')}</em>
            </h2>
            <p className={chapterBody}>{t('landing.company.body')}</p>
            <div className="mt-[35px]">
              <FloorRow code="03" icon={Building2} title={t('landing.company.workTitle')} body={t('landing.company.workBody')} />
              <FloorRow code="02" icon={Orbit} title={t('landing.company.restTitle')} body={t('landing.company.restBody')} />
              <FloorRow code="01" icon={Sparkle} title={t('landing.company.setupTitle')} body={t('landing.company.setupBody')} />
            </div>
          </div>
          <Annotation side="right" kickerText={t('landing.company.annotationKicker')} text={t('landing.company.annotation')} />
        </section>

        {/* 02 · The orbit of work */}
        <section id="working-orbit" className={cn(chapterShell, band)}>
          <div className={cn(chapterCopy, 'border-l border-line-strong py-6 pl-5 md:py-9 md:pl-[34px]', dark ? 'bg-gradient-to-r from-canvas-deep/70 to-transparent' : 'bg-gradient-to-r from-canvas/85 to-transparent')}>
            <span className={kicker}>{t('landing.workflow.kicker')}</span>
            <h2 className={cn(chapterTitle, 'text-[clamp(38px,11vw,56px)] leading-[1.07] md:text-[clamp(43px,4.7vw,70px)]')}>
              {t('landing.workflow.titleA')}
              <br />
              {t('landing.workflow.titleB')} <em className="not-italic text-gold">{t('landing.workflow.titleEm')}</em>
            </h2>
            <p className={chapterBody}>{t('landing.workflow.body')}</p>
            <DemoPanel demo={demo} />
            <button type="button" onClick={enter} className="group inline-flex items-center gap-2.5 border-b border-line-strong py-3 text-[13px] text-ink-strong">
              {t('landing.workflow.link')}
              <SquareKanban className="h-[19px] w-[19px]" strokeWidth={1.5} aria-hidden />
              <ArrowRight className="h-[18px] w-[18px] transition-transform group-hover:translate-x-[5px] motion-reduce:transition-none" aria-hidden />
            </button>
          </div>
          <Annotation side="right" kickerText={t('landing.workflow.annotationKicker')} text={t('landing.workflow.annotation')} />
        </section>

        {/* 03 · The gate */}
        <section id="enter-armarius" className="flex min-h-[88svh] flex-col items-center justify-center px-[25px] pb-[90px] pt-[120px] text-center md:min-h-[92vh]">
          <span className={kicker}>
            <Sparkle className="h-[15px] w-[15px] fill-current" aria-hidden />
            {t('landing.invitation.kicker')}
          </span>
          <h2 className={cn(chapterTitle, 'text-[clamp(40px,12vw,62px)] leading-[1.07] md:text-[clamp(47px,5.6vw,82px)]')}>
            {t('landing.invitation.titleA')}
            <br />
            {t('landing.invitation.titleB')} <em className="not-italic text-gold">{t('landing.invitation.titleEm')}</em>
          </h2>
          <p className={cn(chapterBody, 'mb-[30px]')}>{t('landing.invitation.body')}</p>
          <button type="button" onClick={enter} className="btn btn-primary min-h-[54px] px-6 text-[14px]">
            <Binoculars className="h-[21px] w-[21px]" aria-hidden />
            {t('landing.invitation.cta')}
            <ArrowRight className="h-[19px] w-[19px]" aria-hidden />
          </button>
        </section>
      </main>

      <footer className="relative z-[2] flex flex-col gap-2 border-t border-line px-5 pb-[30px] pt-[22px] font-mono text-[9px] uppercase leading-relaxed tracking-[0.05em] text-ink-muted md:flex-row md:justify-between md:gap-6 md:px-[clamp(24px,4vw,66px)] md:py-[26px] md:text-[10px]">
        <span>{t('landing.footer.brand')}</span>
        <span className="normal-case">{t('landing.footer.tagline')}</span>
      </footer>
    </div>
  );
}
