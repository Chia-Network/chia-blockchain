import React, { useEffect, useMemo, useState } from 'react';
import { Provider } from 'react-redux';
import { I18nProvider } from '@lingui/react';
import useDarkMode from 'use-dark-mode';
import isElectron from 'is-electron';
import { createGlobalStyle } from 'styled-components';
import { ConnectedRouter } from 'connected-react-router';
import { ThemeProvider } from '@chia/core';
import Client, { FullNode, Wallet } from '@chia/api';
import { ApiProvider } from '@reduxjs/toolkit/query/react';
import AppRouter from './AppRouter';
import darkTheme from '../../theme/dark';
import lightTheme from '../../theme/light';
import WebSocketConnection from '../../hocs/WebsocketConnection';
import store, { history } from '../../modules/store';
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
  const [host, setHost] = useState(null);
  const { value: darkMode } = useDarkMode();
  const [locale] = useLocale(defaultLocale);

  const theme = useMemo(() => {
    const material = getMaterialLocale(locale);
    return darkMode ? darkTheme(material) : lightTheme(material);
  }, [locale, darkMode]);

  useEffect(() => {
    activateLocale(locale);
  }, [locale]);

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

  useEffect(async () => {
    await waitForConfig();

    const { remote } = window.require('electron');
    const fs = remote.require('fs');
    const WS = window.require('ws');

    const keyPath = remote.getGlobal('key_path');
    const certPath = remote.getGlobal('cert_path');
    const url = remote.getGlobal('daemon_rpc_ws');

    setHost(url);

    console.log('url', url);
    console.log('keyPath', keyPath);
    console.log('certPath', certPath);

    const client = new Client({
      url,
      cert: fs.readFileSync(certPath),
      key: fs.readFileSync(keyPath),
      WebSocket: WS,
    });

    const fullNode = new FullNode(client);
    const wallet = new Wallet(client);

    await client.connect();
    console.log('get public keys');

    const data = await wallet.getPublicKeys();
    console.log('getPublicKeys', data);

    wallet.onSyncChanged((...args) => {
      console.log('!!!!SYNC CHANGED', ...args);
    });

    wallet.onNewBlock((...args) => {
      console.log('!!!!NEW BLOCK', ...args);
    });

  }, []);

  if (!host) {
    return null;
  }

  return (
      <Provider store={store}>
        <ConnectedRouter history={history}>
          <I18nProvider i18n={i18n}>
            <WebSocketConnection host={host}>
              <ThemeProvider theme={theme}>
                <GlobalStyle />
                <Fonts />
                <AppRouter />
                <AppModalDialogs />
                <AppLoading />
              </ThemeProvider>
            </WebSocketConnection>
          </I18nProvider>
        </ConnectedRouter>
      </Provider>
  );
}
