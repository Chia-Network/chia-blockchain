import React, { ReactNode, useEffect, useState, Suspense } from 'react';
import { Provider } from 'react-redux';
import useDarkMode from 'use-dark-mode';
import { Outlet } from 'react-router-dom';
import { sleep, ThemeProvider, ModalDialogsProvider, ModalDialogs, LocaleProvider, LayoutLoading, dark, light } from '@chia/core';
import { store, api } from '@chia/api-react';
import { Trans } from '@lingui/macro';
import { i18n, defaultLocale, locales } from '../../config/locales';
import AppState from './AppState';

async function waitForConfig() {
  while(true) {
    const config = window.ipcRenderer.invoke('getConfig');
    if (config) {
      return config;
    }

    await sleep(50);
  }
}

type AppProps = {
  outlet?: boolean;
  children?: ReactNode;
};

export default function App(props: AppProps) {
  const { children, outlet } = props;
  const [isReady, setIsReady] = useState<boolean>(false);
  const { value: darkMode } = useDarkMode();

  const theme = darkMode ? dark : light;

  async function init() {
    const config = await waitForConfig();
    const { cert, key, url } = config;
    const WS = window.require('ws');

    store.dispatch(api.initializeConfig({
      url,
      cert,
      key,
      webSocket: WS,
    }));

    setIsReady(true);
  }
  
  useEffect(() => {
    init();
  }, []);

  return (
    <ModalDialogsProvider>
      <Provider store={store}>
        <LocaleProvider i18n={i18n} defaultLocale={defaultLocale} locales={locales}>
          <ThemeProvider theme={theme} fonts global>
            {isReady ? (
              <Suspense fallback={<LayoutLoading />}>
                <AppState>
                  {outlet ? <Outlet /> : children}
                </AppState>
              </Suspense>
            ) : (
              <LayoutLoading>
                <Trans>Loading configuration</Trans>
              </LayoutLoading>
            )}
            <ModalDialogs />
          </ThemeProvider>
        </LocaleProvider>
      </Provider>
    </ModalDialogsProvider>
  );
}
