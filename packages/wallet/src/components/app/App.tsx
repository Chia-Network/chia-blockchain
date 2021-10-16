import React, { useEffect, useMemo, useState } from 'react';
import { Provider } from 'react-redux';
import { I18nProvider } from '@lingui/react';
import useDarkMode from 'use-dark-mode';
import { createHashHistory } from 'history';
import { Router } from 'react-router-dom';
import isElectron from 'is-electron';
import { createGlobalStyle } from 'styled-components';
import { ConnectedRouter } from 'connected-react-router';
import { Loading, ThemeProvider, ModalDialogsProvider, ModalDialogs } from '@chia/core';
import Client, { FullNode, Wallet } from '@chia/api';
import { ApiProvider } from '@reduxjs/toolkit/query/react';
import AppRouter from './AppRouter';
import darkTheme from '../../theme/dark';
import lightTheme from '../../theme/light';
import WebSocketConnection from '../../hocs/WebsocketConnection';
// import store, { history } from '../../modules/store';
import { exit_and_close } from '../../modules/message';
import useLocale from '../../hooks/useLocale';
import AppModalDialogs from './AppModalDialogs';
import AppLoading from './AppLoading';
import {
  i18n,
  activateLocale,
  defaultLocale,
  getMaterialLocale,
} from '../../config/locales';
import Fonts from './fonts/Fonts';
import { store, api } from '@chia/api-react';

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
  const [locale] = useLocale(defaultLocale);

  const theme = useMemo(() => {
    const material = getMaterialLocale(locale);
    return darkMode ? darkTheme(material) : lightTheme(material);
  }, [locale, darkMode]);

  useEffect(() => {
    activateLocale(locale);
  }, [locale]);

  /*
  useEffect(() => {
    window.addEventListener('load', () => {
      if (isElectron()) {
        // @ts-ignore
        window.ipcRenderer.on('exit-daemon', (event) => {
          store.dispatch(exit_and_close(event));
        });
      }
    });
  }, []);
  */

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
    }));

    setIsReady(true);
  }, [config]);


  if (!isReady) {
    return "Loading...";
  }

  return (
    <Provider store={store}>
      <Router history={history}>
        <I18nProvider i18n={i18n}>
          <ThemeProvider theme={theme}>
            <GlobalStyle />
            <Fonts />
            <ModalDialogsProvider>
              <AppRouter />
              {/* <AppLoading /> */}
              <ModalDialogs />
            </ModalDialogsProvider>
          </ThemeProvider>
        </I18nProvider>
      </Router>
    </Provider>
  );
}
