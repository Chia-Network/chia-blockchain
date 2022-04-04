import { useMediaQuery } from '@mui/material';
import useLocalStorage from './useLocalStorage';

const COLOR_SCHEME_QUERY = '(prefers-color-scheme: dark)';

export default function useDarkMode(defaultValue?: boolean): {
  isDarkMode: boolean;
  toggle: () => void;
  enable: () => void;
  disable: () => void;
} {
  const isDarkOS = useMediaQuery(COLOR_SCHEME_QUERY);
  const [isDarkMode, setDarkMode] = useLocalStorage<boolean>(
    'darkMode',
    defaultValue ?? isDarkOS ?? false,
  );

  return {
    isDarkMode,
    toggle: () => setDarkMode(!isDarkMode),
    enable: () => setDarkMode(true),
    disable: () => setDarkMode(false),
  };
}
