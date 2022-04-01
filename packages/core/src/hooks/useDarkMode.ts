import { useCallback } from 'react';
import { useLocalStorage, writeStorage } from '@rehooks/local-storage';
import { useMediaQuery } from '@mui/material';

const LOCAL_STORAGE_KEY = 'darkMode';
const COLOR_SCHEME_QUERY = '(prefers-color-scheme: dark)'

export default function useDarkMode(defaultValue?: boolean): {
  isDarkMode: boolean;
  toggle: () => void;
  enable: () => void;
  disable: () => void;
} {
  const isDarkOS = useMediaQuery(COLOR_SCHEME_QUERY)
  const [isDarkMode] = useLocalStorage<boolean>(
    LOCAL_STORAGE_KEY, 
    defaultValue ?? isDarkOS ?? false,
  );

  const setDarkMode = useCallback((darkMode: boolean) => {
    writeStorage(LOCAL_STORAGE_KEY, darkMode);
  }, []);

  return {
    isDarkMode,
    toggle: () => setDarkMode(!isDarkMode),
    enable: () => setDarkMode(true),
    disable: () => setDarkMode(false),
  };
}
