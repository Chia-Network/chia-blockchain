import React from 'react';
import { ThemeProvider, StylesProvider } from "@material-ui/core/styles";
import { Provider } from "react-redux";
import { ModalDialog, Spinner } from '../pages/ModalDialog';
import Router from './Router';
import theme from '../theme/default';
import WebSocketConnection from "../hocs/WebsocketConnection";
import { daemon_rpc_ws } from "../util/config";
import store from "../modules/store";

export default function App() {
  return (
    <Provider store={store}>
      <WebSocketConnection host={daemon_rpc_ws}>
        <StylesProvider injectFirst>
          <ThemeProvider theme={theme}>
            <ModalDialog />
            <Spinner />
            <Router />
          </ThemeProvider>
        </StylesProvider>
      </WebSocketConnection>
    </Provider>
  );
}
