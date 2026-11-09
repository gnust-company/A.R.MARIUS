import { useAppStore } from '@/store/appStore';
import { useNavigate } from 'react-router';
import { motion } from 'framer-motion';
import type { ReactNode } from 'react';
import { BookOpen, Check, Globe, LogOut, User } from 'lucide-react';
import PageTitle from '@/components/PageTitle';
import { Sigil } from '@/components/Brand';
import { cn } from '@/lib/utils';
import { useTranslation } from 'react-i18next';

/** One settings block: an eyebrow-sized icon line, a Lora heading, then whatever it holds. */
function Section({
  icon: Icon,
  title,
  description,
  children,
}: {
  icon: typeof User;
  title: string;
  description?: string;
  children: ReactNode;
}) {
  return (
    <section className="surface px-[18px] py-5 sm:px-6 sm:py-[22px]">
      <div className="flex items-center gap-2.5">
        <Icon className="h-[18px] w-[18px] shrink-0 text-ink-muted" aria-hidden />
        <h2 className="font-display text-[21px] font-normal tracking-[-0.01em] text-ink-strong">{title}</h2>
      </div>
      {description && <p className="mt-1.5 font-body text-body-sm text-ink-light">{description}</p>}
      <div className="mt-4">{children}</div>
    </section>
  );
}

export default function Account() {
  const { currentUser, logout } = useAppStore();
  const navigate = useNavigate();
  const { i18n, t } = useTranslation();

  const handleSignOut = () => {
    logout();
    navigate('/workspaces');
  };

  const currentLang = i18n.language || 'en';

  // A two-way choice, drawn as the design's segmented control: the chosen side is sapphire-soft.
  const langButton = (active: boolean) =>
    cn(
      'btn min-w-[132px] border',
      active
        ? 'border-sapphire bg-sapphire-soft text-ink-strong'
        : 'border-line-strong bg-surface text-ink-light hover:enabled:border-sapphire hover:enabled:text-ink-strong'
    );

  return (
    <motion.div
      initial={{ opacity: 0, y: 6 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.2 }}
      className="mx-auto flex w-full max-w-3xl flex-col gap-6 pb-10"
    >
      <PageTitle eyebrow={t('account.eyebrow')} title={t('nav.account')} subtitle={t('account.subtitle')} />

      <div className="flex flex-col gap-4">
        <Section icon={User} title={t('account.profile')}>
          <div className="flex min-w-0 items-center gap-4">
            <span className="flex h-14 w-14 shrink-0 items-center justify-center rounded-full border border-gold/40 bg-gold-soft font-display text-[22px] font-normal text-gold">
              {(currentUser?.name?.[0] || 'P').toUpperCase()}
            </span>
            <div className="min-w-0">
              <p className="truncate font-display text-[20px] font-normal text-ink-strong">
                {currentUser?.name || t('account.patron')}
              </p>
              <p className="truncate font-body text-body-sm text-ink-light">
                {currentUser?.email || 'patron@armarius.local'}
              </p>
              <span className="status-pill mt-2 border-gold/35 text-gold">
                <span className="status-dot bg-gold" aria-hidden />
                {t('account.patron')}
              </span>
            </div>
          </div>
        </Section>

        <Section icon={Globe} title={t('account.languageSection')} description={t('account.languageDesc')}>
          <div role="group" aria-label={t('account.languageSection')} className="flex flex-wrap gap-2">
            <button
              type="button"
              onClick={() => i18n.changeLanguage('en')}
              aria-pressed={currentLang === 'en'}
              className={langButton(currentLang === 'en')}
            >
              {currentLang === 'en' && <Check className="h-4 w-4 text-sapphire-strong" aria-hidden />}
              {t('account.english')}
            </button>
            <button
              type="button"
              onClick={() => i18n.changeLanguage('vi')}
              aria-pressed={currentLang === 'vi'}
              className={langButton(currentLang === 'vi')}
            >
              {currentLang === 'vi' && <Check className="h-4 w-4 text-sapphire-strong" aria-hidden />}
              {t('account.vietnamese')}
            </button>
          </div>
        </Section>

        <Section icon={LogOut} title={t('account.session')} description={t('account.sessionDesc')}>
          <button type="button" onClick={handleSignOut} className="btn btn-secondary">
            <LogOut className="h-4 w-4" aria-hidden /> {t('account.signOut')}
          </button>
        </Section>

        <Section icon={BookOpen} title={t('account.about')}>
          <div className="flex items-center gap-3">
            <Sigil className="h-10 w-10 shrink-0" />
            <div className="min-w-0">
              <p className="font-display text-[20px] font-normal text-ink-strong">{t('app.name')}</p>
              <p className="mt-0.5 font-mono text-mono-sm text-ink-muted">A.R.MARIUS — v1.0.0</p>
            </div>
          </div>
          <p className="mt-3 border-l-2 border-gold/50 pl-3 font-display text-[16px] italic text-ink-light">
            &ldquo;{t('app.tagline')}&rdquo;
          </p>
        </Section>
      </div>
    </motion.div>
  );
}
