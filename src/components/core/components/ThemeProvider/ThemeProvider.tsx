import React, { ReactNode } from 'react';
import { CssBaseline } from '@material-ui/core';
import {
  ThemeProvider as MaterialThemeProvider,
  StylesProvider,
} from '@material-ui/core/styles';
import { ThemeProvider as StyledThemeProvider } from 'styled-components';


type Props = {
  children: ReactNode;
  theme: Object;
};

export default function ThemeProvider(props: Props) {
  const { children, theme } = props;

  return (
    <StylesProvider injectFirst>
      <StyledThemeProvider theme={theme}>
        <MaterialThemeProvider theme={theme}>
          <>
            <CssBaseline />
            {children}
          </>
        </MaterialThemeProvider>
      </StyledThemeProvider>
    </StylesProvider>
  );
}
