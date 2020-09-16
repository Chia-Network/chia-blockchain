import React from 'react';
import { ThemeProvider } from "@material-ui/core/styles";
import { ModalDialog, Spinner } from '../pages/ModalDialog';
import Router from './Router';
import theme from '../theme/default';

export default function App() {
  return (
    <ThemeProvider theme={theme}>
      <ModalDialog />
      <Spinner />
      <Router />
    </ThemeProvider>
  );
};
