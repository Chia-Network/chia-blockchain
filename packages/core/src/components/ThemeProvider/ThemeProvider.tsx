import React, { useMemo, ReactNode } from 'react';
import { CssBaseline } from '@material-ui/core';
import {
  ThemeProvider as MaterialThemeProvider,
  StylesProvider,
  createTheme,
} from '@material-ui/core/styles';
import * as materialLocales from '@material-ui/core/locale';
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
    <StylesProvider injectFirst>
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
    </StylesProvider>
  );
}

ThemeProvider.defaultProps = {
  fonts: false,
  global: false,
};
