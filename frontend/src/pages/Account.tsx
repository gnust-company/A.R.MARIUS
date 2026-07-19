// @ts-nocheck
import { useAppStore } from '@/store/appStore';
import { useNavigate } from 'react-router';
import { motion } from 'framer-motion';
import { LogOut, Globe, User, BookOpen } from 'lucide-react';
import VellumPanel from '@/components/VellumPanel';
import PageTitle from '@/components/PageTitle';
import { useTranslation } from 'react-i18next';

const quillIn = {
  hidden: { opacity: 0, y: 20, filter: 'blur(2px)' },
  visible: (i: number) => ({
    opacity: 1, y: 0, filter: 'blur(0px)',
    transition: { delay: 0.1 + i * 0.1, duration: 0.5, ease: [0, 0, 0.2, 1] as [number, number, number, number] },
  }),
};

export default function Account() {
  const { currentUser, logout } = useAppStore();
  const navigate = useNavigate();
  const { i18n, t } = useTranslation();

  const handleSignOut = () => {
    logout();
    navigate('/workspaces');
  };

  const currentLang = i18n.language || 'en';

  return (
    <div className="max-w-2xl mx-auto">
      {/* Header */}
      <motion.div
        initial={{ opacity: 0, y: -8 }}
        animate={{ opacity: 1, y: 0 }}
        className="flex items-center gap-3 mb-8"
      >
        <PageTitle title={t('nav.account')} subtitle={t('account.subtitle')} />
      </motion.div>

      <div className="space-y-6">
        {/* Profile Section */}
        <motion.div custom={0} variants={quillIn} initial="hidden" animate="visible">
          <VellumPanel>
            <div className="flex items-center gap-2 mb-4">
              <User size={18} className="text-[#C25E3A]" />
              <h2 className="text-lg font-medium text-[#2A2318] font-[Fraunces]">{t('account.profile')}</h2>
            </div>
            <div className="flex items-center gap-4">
              <div className="w-16 h-16 rounded-full bg-[#EDE4CE] border-2 border-[#D4A843] flex items-center justify-center text-xl font-[Fraunces] text-[#C25E3A]">
                {currentUser?.name?.[0] || 'P'}
              </div>
              <div>
                <p className="font-medium text-[#2A2318] font-[Fraunces] text-lg">
                  {currentUser?.name || t('account.patron')}
                </p>
                <p className="text-sm text-[#6B5E4E]">{currentUser?.email || 'patron@armarius.local'}</p>
                <span className="inline-block mt-1 px-2 py-0.5 text-xs font-medium bg-[#C25E3A]/10 text-[#C25E3A] rounded-full">
                  {t('account.patron')}
                </span>
              </div>
            </div>
          </VellumPanel>
        </motion.div>

        {/* Language Section */}
        <motion.div custom={1} variants={quillIn} initial="hidden" animate="visible">
          <VellumPanel>
            <div className="flex items-center gap-2 mb-4">
              <Globe size={18} className="text-[#C25E3A]" />
              <h2 className="text-lg font-medium text-[#2A2318] font-[Fraunces]">{t('account.languageSection')}</h2>
            </div>
            <p className="text-sm text-[#6B5E4E] mb-4">{t('account.languageDesc')}</p>
            <div className="flex gap-3">
              <button
                onClick={() => i18n.changeLanguage('en')}
                className={`px-6 py-2.5 rounded-lg text-sm font-medium border-2 transition-all ${
                  currentLang === 'en'
                    ? 'border-[#C25E3A] bg-[#C25E3A] text-white shadow-sm'
                    : 'border-[#E3D7BC] text-[#6B5E4E] hover:border-[#C25E3A]/40 hover:bg-[#EDE4CE]'
                }`}
              >
                {t('account.english')}
              </button>
              <button
                onClick={() => i18n.changeLanguage('vi')}
                className={`px-6 py-2.5 rounded-lg text-sm font-medium border-2 transition-all ${
                  currentLang === 'vi'
                    ? 'border-[#C25E3A] bg-[#C25E3A] text-white shadow-sm'
                    : 'border-[#E3D7BC] text-[#6B5E4E] hover:border-[#C25E3A]/40 hover:bg-[#EDE4CE]'
                }`}
              >
                {t('account.vietnamese')}
              </button>
            </div>
          </VellumPanel>
        </motion.div>

        {/* Session Section */}
        <motion.div custom={2} variants={quillIn} initial="hidden" animate="visible">
          <VellumPanel>
            <div className="flex items-center gap-2 mb-4">
              <LogOut size={18} className="text-[#C25E3A]" />
              <h2 className="text-lg font-medium text-[#2A2318] font-[Fraunces]">{t('account.session')}</h2>
            </div>
            <p className="text-sm text-[#6B5E4E] mb-4">{t('account.sessionDesc')}</p>
            <button
              onClick={handleSignOut}
              className="px-5 py-2.5 text-sm font-medium text-[#C25E3A] border-2 border-[#C25E3A] rounded-lg hover:bg-[#C25E3A] hover:text-white transition-colors"
            >
              <span className="flex items-center gap-2">
                <LogOut size={16} /> {t('account.signOut')}
              </span>
            </button>
          </VellumPanel>
        </motion.div>

        {/* About Section */}
        <motion.div custom={3} variants={quillIn} initial="hidden" animate="visible">
          <VellumPanel>
            <div className="flex items-center gap-2 mb-4">
              <BookOpen size={18} className="text-[#D4A843]" />
              <h2 className="text-lg font-medium text-[#2A2318] font-[Fraunces]">{t('account.about')}</h2>
            </div>
            <div className="flex items-center gap-3">
              <span className="text-2xl text-[#D4A843]">&#9670;</span>
              <div>
                <p className="font-[Fraunces] text-xl text-[#2A2318]">{t('app.name')}</p>
                <p className="font-mono text-xs text-[#A89880] mt-0.5">A.R.MARIUS — v1.0.0</p>
              </div>
            </div>
            <p className="text-sm text-[#6B5E4E] mt-3 italic">
              &ldquo;{t('app.tagline')}&rdquo;
            </p>
          </VellumPanel>
        </motion.div>
      </div>
    </div>
  );
}
