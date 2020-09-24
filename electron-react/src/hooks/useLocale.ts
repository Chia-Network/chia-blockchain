import { useLocalStorage } from 'react-use';

export type Locales = 'en' | 'sk';

export default function useLocale(defaultLocale: Locales): [Locales, (locale: Locales) => void] {
  const [locale, setLocale] = useLocalStorage<Locales>('locale', defaultLocale);

  return [locale || defaultLocale, setLocale];
}