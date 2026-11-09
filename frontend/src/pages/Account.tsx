import { useAppStore } from '@/store/appStore';
import { useNavigate } from 'react-router';
import { motion } from 'framer-motion';
import type { ReactNode } from 'react';
import { BookOpen, Check, Globe, LogOut, User } from 'lucide-react';
import PageTitle from '@/components/PageTitle';
import { cn } from '@/lib/utils';
import { useTranslation } from 'react-i18next';

/** One settings block: a heading with its icon, then whatever the block holds. */
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
    <section className="bg-paper border border-line rounded-xl px-5 py-5 sm:px-6">
      <div className="flex items-center gap-2.5">
        <Icon className="w-[18px] h-[18px] text-ink-muted shrink-0" aria-hidden />
        <h2 className="font-display text-[20px] font-medium text-ink">{title}</h2>
      </div>
      {description && <p className="mt-1 font-body text-body-md text-ink-light">{description}</p>}
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

  const langButton = (active: boolean) =>
    cn(
      'inline-flex items-center justify-center gap-2 min-h-[44px] px-5 rounded-md border font-body text-body-md font-medium transition-colors',
      active ? 'bg-ink text-paper border-ink' : 'bg-paper text-ink border-line-strong hover:bg-inset'
    );

  return (
    <motion.div
      initial={{ opacity: 0, y: 6 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.2 }}
      className="mx-auto w-full max-w-3xl flex flex-col gap-6 pb-10"
    >
      <PageTitle title={t('nav.account')} subtitle={t('account.subtitle')} />

      <div className="flex flex-col gap-4">
        <Section icon={User} title={t('account.profile')}>
          <div className="flex items-center gap-4 min-w-0">
            <span className="w-14 h-14 shrink-0 rounded-full bg-gold-bg text-gold-ink ring-2 ring-gold ring-offset-2 ring-offset-paper flex items-center justify-center font-display text-[22px] font-medium">
              {(currentUser?.name?.[0] || 'P').toUpperCase()}
            </span>
            <div className="min-w-0">
              <p className="font-display text-[20px] font-medium text-ink truncate">
                {currentUser?.name || t('account.patron')}
              </p>
              <p className="font-body text-body-md text-ink-light truncate">
                {currentUser?.email || 'patron@armarius.local'}
              </p>
              <span className="inline-flex mt-1.5 px-2.5 py-0.5 rounded-full bg-ash-bg font-body text-body-sm font-medium text-ink-light">
                {t('account.patron')}
              </span>
            </div>
          </div>
        </Section>

        <Section icon={Globe} title={t('account.languageSection')} description={t('account.languageDesc')}>
          <div role="group" aria-label={t('account.languageSection')} className="flex flex-wrap gap-2">
            <button
              onClick={() => i18n.changeLanguage('en')}
              aria-pressed={currentLang === 'en'}
              className={langButton(currentLang === 'en')}
            >
              {currentLang === 'en' && <Check className="w-4 h-4" aria-hidden />}
              {t('account.english')}
            </button>
            <button
              onClick={() => i18n.changeLanguage('vi')}
              aria-pressed={currentLang === 'vi'}
              className={langButton(currentLang === 'vi')}
            >
              {currentLang === 'vi' && <Check className="w-4 h-4" aria-hidden />}
              {t('account.vietnamese')}
            </button>
          </div>
        </Section>

        <Section icon={LogOut} title={t('account.session')} description={t('account.sessionDesc')}>
          <button
            onClick={handleSignOut}
            className="inline-flex items-center gap-2 min-h-[44px] px-4 rounded-md border border-line-strong bg-paper font-body text-body-md font-medium text-ink hover:bg-inset transition-colors"
          >
            <LogOut className="w-4 h-4" aria-hidden /> {t('account.signOut')}
          </button>
        </Section>

        <Section icon={BookOpen} title={t('account.about')}>
          <div className="flex items-center gap-3">
            <span className="text-2xl text-gold" aria-hidden>&#9670;</span>
            <div className="min-w-0">
              <p className="font-display text-[20px] font-medium text-ink">{t('app.name')}</p>
              <p className="font-mono text-mono-sm text-ink-muted mt-0.5">A.R.MARIUS — v1.0.0</p>
            </div>
          </div>
          <p className="mt-3 font-body text-body-md italic text-ink-light">&ldquo;{t('app.tagline')}&rdquo;</p>
        </Section>
      </div>
    </motion.div>
  );
}
