import React, { useEffect, useState } from 'react';
import { Provider } from 'react-redux';
import useDarkMode from 'use-dark-mode';
import { Outlet } from 'react-router-dom';
import { sleep, Loading, ThemeProvider, ModalDialogsProvider, ModalDialogs, LocaleProvider } from '@chia/core';
import { store, api } from '@chia/api-react';
import { ServiceName } from '@chia/api';
import { Trans } from '@lingui/macro';
import LayoutHero from '../layout/LayoutHero';
import darkTheme from '../../theme/dark';
import lightTheme from '../../theme/light';
import { i18n, defaultLocale, locales } from '../../config/locales';
import AppState from './AppState';
import { or } from 'make-plural';

async function waitForConfig() {
  while(true) {
    const config = window.ipcRenderer.invoke('getConfig');
    if (config) {
      return config;
    }

    await sleep(50);
  }
}

export default function App(props) {
  const { children } = props;
  const [isReady, setIsReady] = useState<boolean>(false);
  const { value: darkMode } = useDarkMode();

  const theme = darkMode ? darkTheme : lightTheme;

  async function init() {
    const config = await waitForConfig();
    const { cert, key, url } = config;
    const WS = window.require('ws');

    store.dispatch(api.initializeConfig({
      url,
      cert,
      key,
      webSocket: WS,
      services: config.local_test ? [
        ServiceName.WALLET,
        ServiceName.SIMULATOR,
      ] : [
        ServiceName.WALLET, 
        ServiceName.FULL_NODE,
        ServiceName.FARMER,
        ServiceName.HARVESTER,
      ],
    }));

    setIsReady(true);
  }
  
  useEffect(() => {
    init();
  }, []);

  return (
    <Provider store={store}>
      <LocaleProvider i18n={i18n} defaultLocale={defaultLocale} locales={locales}>
        <ThemeProvider theme={theme} fonts global>
          {isReady ? (
            <AppState>
              <ModalDialogsProvider>
                <Outlet />
                {children}
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
    </Provider>
  );
}
