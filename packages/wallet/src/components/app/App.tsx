import React, { useEffect, useState } from 'react';
import { Provider } from 'react-redux';
import useDarkMode from 'use-dark-mode';
import { createHashHistory } from 'history';
import { Router } from 'react-router-dom';
import { Loading, LocaleProvider, ThemeProvider, ModalDialogsProvider, ModalDialogs, useLocale } from '@chia/core';
import { store, api } from '@chia/api-react';
import { ServiceName } from '@chia/api';
import { Trans } from '@lingui/macro';
import LayoutHero from '../layout/LayoutHero';
import AppRouter from './AppRouter';
import darkTheme from '../../theme/dark';
import lightTheme from '../../theme/light';
import { i18n, defaultLocale, locales } from '../../config/locales';
import AppState from './AppState';

export const history = createHashHistory();

async function waitForConfig() {
  const { remote } = window.require('electron');

  let keyPath = null;

  while(true) {
    keyPath = remote.getGlobal('key_path');
    if (keyPath) {
      return;
    }

    await new Promise((resolve) => {
      setTimeout(resolve, 50);
    });
  }
}

export default function App() {
  const [isReady, setIsReady] = useState<boolean>(false);
  const { value: darkMode } = useDarkMode();

  const theme = darkMode 
    ? darkTheme 
    : lightTheme;

  const { api: { config } } = store.getState();
  
  useEffect(async () => {
    if (config) {
      setIsReady(true);
      return;
    }

    await waitForConfig();

    const { remote } = window.require('electron');
    const fs = remote.require('fs');
    const WS = window.require('ws');

    const keyPath = remote.getGlobal('key_path');
    const certPath = remote.getGlobal('cert_path');
    const url = remote.getGlobal('daemon_rpc_ws');

    store.dispatch(api.initializeConfig({
      url,
      cert: fs.readFileSync(certPath).toString(),
      key: fs.readFileSync(keyPath).toString(),
      webSocket: WS,
      services: [ServiceName.WALLET],
    }));

    setIsReady(true);
  }, [config]);

  return (
    <Provider store={store}>
      <Router history={history}>
        <LocaleProvider i18n={i18n} defaultLocale={defaultLocale} locales={locales}>
          <ThemeProvider theme={theme} global fonts>
            {isReady ? (
              <AppState>
                <ModalDialogsProvider>
                  <AppRouter />
                  <ModalDialogs />
                </ModalDialogsProvider>
              </AppState>
            ) : (
              <LayoutHero>
                <Loading center>
                  <Trans>Loading configuration</Trans>
                </Loading>
              </LayoutHero>
            )}
          </ThemeProvider>
        </LocaleProvider>
      </Router>
    </Provider>
  );
}
