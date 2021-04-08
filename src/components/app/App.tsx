import React, { useEffect, useState } from 'react';
import { Provider } from 'react-redux';
import { I18nProvider } from '@lingui/react';
import { deDE, enUS, zhCN, esES, frFR, fiFI, itIT, jaJP, nlNL, ptBR, ptPT, plPL, roRO, ruRU, skSK, svSE, viVN } from '@material-ui/core/locale';
import useDarkMode from 'use-dark-mode';
import isElectron from 'is-electron';
import { createGlobalStyle } from 'styled-components'
import { ConnectedRouter } from 'connected-react-router';
import { ThemeProvider } from '@chia/core';
import AppRouter from './AppRouter';
import darkTheme from '../../theme/dark';
import lightTheme from '../../theme/light';
import WebSocketConnection from '../../hocs/WebsocketConnection';
import store, { history } from '../../modules/store';
import { exit_and_close } from '../../modules/message';
import useLocale from '../../hooks/useLocale';
import AppModalDialogs from './AppModalDialogs';
import AppLoading from './AppLoading';
import i18n from '../../config/locales';
import Fonts from './fonts/Fonts';
import TimeBomb from './AppTimeBomb';

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
`;

function localeToMaterialLocale(locale: string): object {
  switch (locale) {
    case 'de-DE':
      return deDE;
    case 'en-US':
      return enUS;
    case 'es-ES':
      return esES;
    case 'fr-FR':
      return frFR;
    case 'it-IT':
      return itIT;
    case 'ja-JP':
      return jaJP;
    case 'nl-NL':
      return nlNL;
    case 'fi-FI':
      return fiFI;
    case 'pl-PL':
      return plPL;
    case 'pt-BR':
      return ptBR;
    case 'pt-PT':
      return ptPT;
    case 'ro-RO':
      return roRO;
    case 'ru-RU':
      return ruRU;
    case 'sk-SK':
      return skSK;
    case 'sv-SE':
      return svSE;
    case 'vi-VN':
      return viVN;
    case 'zh-TW':
    case 'zh-CN':
      return zhCN;
    default:
      return enUS;
  }
}

export default function App() {
  const { value: darkMode } = useDarkMode();
  const [locale] = useLocale('en-US');
  const [theme, setTheme] = useState(lightTheme(localeToMaterialLocale(locale)));

  // get the daemon's uri from global storage (put there by loadConfig)
  let daemon_uri = null;
  if (isElectron()) {
    const electron = window.require('electron');
    const { remote : r } = electron;
    daemon_uri = r.getGlobal('daemon_rpc_ws');
  }

  useEffect(() => {
    i18n.activate(locale);
    // @ts-ignore
    window.ipcRenderer.send("set-locale", locale)
    if (darkMode) {
      setTheme(darkTheme(localeToMaterialLocale(locale)));
    } else {
      setTheme(lightTheme(localeToMaterialLocale(locale)));
    }
    moment.locale([locale, 'en']);
  }, [locale, darkMode]);

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
        <I18nProvider i18n={i18n}>
          <WebSocketConnection host={daemon_uri}>
            <ThemeProvider theme={theme}>
              <GlobalStyle />
              <Fonts />
              <TimeBomb />
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
