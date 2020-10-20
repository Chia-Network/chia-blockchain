import React from 'react';
import { CssBaseline } from "@material-ui/core";
import { Provider } from "react-redux";
import { I18nProvider } from '@lingui/react';
import useDarkMode from 'use-dark-mode';
import { ModalDialog, Spinner } from '../../pages/ModalDialog';
import Router from '../router/Router';
import darkTheme from '../../theme/dark';
import lightTheme from '../../theme/light';
import WebSocketConnection from "../../hocs/WebsocketConnection";
import { daemon_rpc_ws } from "../../util/config";
import store from "../../modules/store";
import ThemeProvider from '../theme/ThemeProvider';
import en from '../../locales/en/messages';
import sk from '../../locales/sk/messages';
import styles from './App.module.css';

const catalogs = {
  en,
  sk,
};

export default function App() {
  const { value: darkMode } = useDarkMode(false);

  return (
    <Provider store={store}>
      <I18nProvider language="en" catalogs={catalogs}>
        <WebSocketConnection host={daemon_rpc_ws}>
          <ThemeProvider theme={darkMode ? darkTheme : lightTheme}>
            <CssBaseline />
            <ModalDialog />
            <Spinner />
            <Router />
          </ThemeProvider>
        </WebSocketConnection>
      </I18nProvider>
    </Provider>
  );
}

App.styles = styles;
