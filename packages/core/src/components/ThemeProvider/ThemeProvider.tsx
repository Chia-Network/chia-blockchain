import React, { useMemo, ReactNode } from 'react';
import { CssBaseline } from '@mui/material';
import {
  ThemeProvider as MaterialThemeProvider,
  createTheme,
} from '@mui/material/styles';
import * as materialLocales from '@mui/material/locale';
import { ThemeProvider as StyledThemeProvider, createGlobalStyle } from 'styled-components';
import Fonts from '../Fonts';
import useLocale from '../../hooks/useLocale';

export function getMaterialLocale(locale: string) {
  if (!locale) {
    return materialLocales.enUS;
  }

  const materialLocale = locale.replace('-', '');
  return materialLocales[materialLocale] ?? materialLocales.enUS;
}

const GlobalStyle = createGlobalStyle`
  html,
  body,
  #root {
    height: 100%;
  }

  #root {
    display: flex;
    flex-direction: column;
  }

  ul .MuiBox-root {
    outline: none;
  }
`;

export type ThemeProviderProps = {
  children: ReactNode;
  theme: Object;
  fonts?: boolean;
  global?: boolean;
};

export default function ThemeProvider(props: ThemeProviderProps) {
  const { children, theme, global, fonts } = props;
  const [locale] = useLocale();

  const finallTheme = useMemo(() => {
    const localisedTheme = getMaterialLocale(locale);
    return createTheme(theme, localisedTheme);
  }, [theme, locale]);

  return (
    <StyledThemeProvider theme={finallTheme}>
      <MaterialThemeProvider theme={finallTheme}>
        <>
          <CssBaseline />
          {global && (
            <GlobalStyle />
          )}
          {fonts && (
            <Fonts />
          )}
          {children}
        </>
      </MaterialThemeProvider>
    </StyledThemeProvider>
  );
}

ThemeProvider.defaultProps = {
  fonts: false,
  global: false,
};
