import React, { ReactNode } from 'react';
import { ThemeProvider as StyledThemeProvider } from 'styled-components';
import {
  ThemeProvider as MaterialThemeProvider,
  StylesProvider,
} from '@material-ui/core';

type Props = {
  children: ReactNode;
  theme: Object;
};

export default function ThemeProvider(props: Props) {
  const { children, theme } = props;

  return (
    <StylesProvider injectFirst>
      <StyledThemeProvider theme={theme}>
        <MaterialThemeProvider theme={theme}>{children}</MaterialThemeProvider>
      </StyledThemeProvider>
    </StylesProvider>
  );
}
