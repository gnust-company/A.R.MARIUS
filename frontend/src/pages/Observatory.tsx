import { useTranslation } from 'react-i18next';
import PageTitle from '@/components/PageTitle';

/** Placeholder until the 3D observatory scene lands. */
export default function Observatory() {
  const { t } = useTranslation();
  return <PageTitle title={t('nav.observatory')} />;
}
