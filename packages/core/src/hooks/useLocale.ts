import { useContext } from 'react';
import { LocaleContext } from '../components/LocaleProvider';

export default function useLocale(): [string, (locale: string) => void] {
  const localeContext = useContext(LocaleContext);

  if (!localeContext) {
    throw new Error('You need to use LocaleProvider.');
  }

  const { locale, setLocale } = localeContext;

  return [locale, setLocale];
}
