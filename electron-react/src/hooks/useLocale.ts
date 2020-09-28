import { useLocalStorage, writeStorage } from '@rehooks/local-storage';

export default function useLocale(
  defaultLocale: string,
): [string, (locale: string) => void] {
  const [locale] = useLocalStorage('locale');

  function handleSetLocale(locale: string) {
    writeStorage('locale', locale);
  }

  return [locale ?? defaultLocale, handleSetLocale];
}
