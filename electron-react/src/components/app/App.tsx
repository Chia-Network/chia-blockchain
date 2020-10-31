import React, { useEffect } from 'react';
import { CssBaseline } from '@material-ui/core';
import { Provider, useSelector, useDispatch } from 'react-redux';
import { I18nProvider } from '@lingui/react';
import useDarkMode from 'use-dark-mode';
import isElectron from 'is-electron';
import { ConnectedRouter } from 'connected-react-router';
import { ModalDialogs, Spinner, ThemeProvider } from '@chia/core';
import Router from '../router/Router';
import darkTheme from '../../theme/dark';
import lightTheme from '../../theme/light';
import WebSocketConnection from '../../hocs/WebsocketConnection';
import { daemon_rpc_ws } from '../../util/config';
import store, { history } from '../../modules/store';
import { exit_and_close } from '../../modules/message';
import { closeDialog } from '../../modules/dialog';
import en from '../../locales/en/messages';
import sk from '../../locales/sk/messages';
import useLocale from '../../hooks/useLocale';
import './App.css';
import { RootState } from '../../modules/rootReducer';

const catalogs = {
  en,
  sk,
};

export default function App() {
  const { value: darkMode } = useDarkMode();
  const dialogs = useSelector((state: RootState) => state.dialog_state.dialogs);
  const showProgressIndicator = useSelector((state: RootState) => state.progress.progress_indicator);
  const [locale] = useLocale('en');

  const dispatch = useDispatch();

  function handleCloseDialog(id: number) {
    dispatch(closeDialog(id));
  }

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
              <CssBaseline />
              <ModalDialogs dialogs={dialogs} onClose={handleCloseDialog} />
              <Spinner show={showProgressIndicator} />
              <Router />
            </ThemeProvider>
          </WebSocketConnection>
        </I18nProvider>
      </ConnectedRouter>
    </Provider>
  );
}
