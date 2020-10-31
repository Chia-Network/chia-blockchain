import React, { useEffect } from 'react';
import { Provider } from 'react-redux';
import { I18nProvider } from '@lingui/react';
import useDarkMode from 'use-dark-mode';
import isElectron from 'is-electron';
import { ConnectedRouter } from 'connected-react-router';
import { ThemeProvider } from '@chia/core';
import AppRouter from './AppRouter';
import darkTheme from '../../theme/dark';
import lightTheme from '../../theme/light';
import WebSocketConnection from '../../hocs/WebsocketConnection';
import { daemon_rpc_ws } from '../../util/config';
import store, { history } from '../../modules/store';
import { exit_and_close } from '../../modules/message';
import en from '../../locales/en/messages';
import sk from '../../locales/sk/messages';
import useLocale from '../../hooks/useLocale';
import './App.css';
import AppModalDialogs from './AppModalDialogs';
import AppLoading from './AppLoading';

const catalogs = {
  en,
  sk,
};

export default function App() {
  const { value: darkMode } = useDarkMode();
  const [locale] = useLocale('en');

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

  return (
    <Provider store={store}>
      <ConnectedRouter history={history}>
        <I18nProvider language={locale} catalogs={catalogs}>
          <WebSocketConnection host={daemon_rpc_ws}>
            <ThemeProvider theme={darkMode ? darkTheme : lightTheme}>
              <AppModalDialogs />
              <AppLoading />
              <AppRouter />
            </ThemeProvider>
          </WebSocketConnection>
        </I18nProvider>
      </ConnectedRouter>
    </Provider>
  );
}
