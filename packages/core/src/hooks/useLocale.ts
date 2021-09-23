import { useLocalStorage, writeStorage } from '@rehooks/local-storage';

export default function useLocale(
  defaultLocale: string,
): [string, (locale: string) => void] {
  let [locale] = useLocalStorage<string>('locale', defaultLocale);

  if (locale && locale.length === 2) {
    locale = defaultLocale;
  }

  function handleSetLocale(locale: string) {
    writeStorage('locale', locale);
  }

  return [locale, handleSetLocale];
}
