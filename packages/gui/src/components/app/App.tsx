import React, { useEffect, useMemo, useState } from 'react';
import { Provider } from 'react-redux';
import { I18nProvider } from '@lingui/react';
import useDarkMode from 'use-dark-mode';
import { createHashHistory } from 'history';
import { Router } from 'react-router-dom';
import { createGlobalStyle } from 'styled-components';
import { sleep, Loading, ThemeProvider, ModalDialogsProvider, ModalDialogs } from '@chia/core';
import { store, api } from '@chia/api-react';
import { ServiceName } from '@chia/api';
import { Trans } from '@lingui/macro';
import LayoutHero from '../layout/LayoutHero';
import AppRouter from './AppRouter';
import darkTheme from '../../theme/dark';
import lightTheme from '../../theme/light';
import useLocale from '../../hooks/useLocale';
import {
  i18n,
  activateLocale,
  defaultLocale,
  getMaterialLocale,
} from '../../config/locales';
import Fonts from './fonts/Fonts';
import AppState from './AppState';

export const history = createHashHistory();

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

async function waitForConfig() {
  while(true) {
    const config = window.ipcRenderer.invoke('getConfig');
    if (config) {
      return config;
    }

    await sleep(50);
  }
}

export default function App() {
  const [isReady, setIsReady] = useState<boolean>(false);
  const { value: darkMode } = useDarkMode();
  const [locale] = useLocale(defaultLocale);

  const theme = useMemo(() => {
    const material = getMaterialLocale(locale);
    return darkMode ? darkTheme(material) : lightTheme(material);
  }, [locale, darkMode]);

  useEffect(() => {
    activateLocale(locale);
  }, [locale]);

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
      <Router history={history}>
        <I18nProvider i18n={i18n}>
          <ThemeProvider theme={theme}>
            <GlobalStyle />
            <Fonts />
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
        </I18nProvider>
      </Router>
    </Provider>
  );
}
