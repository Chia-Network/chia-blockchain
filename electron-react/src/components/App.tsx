import React from 'react';
import { CssBaseline } from "@material-ui/core";
import { Provider } from "react-redux";
import { ModalDialog, Spinner } from '../pages/ModalDialog';
import Router from './Router';
import theme from '../theme/light';
import WebSocketConnection from "../hocs/WebsocketConnection";
import { daemon_rpc_ws } from "../util/config";
import store from "../modules/store";
import ThemeProvider from './theme/ThemeProvider';

export default function App() {
  return (
    <Provider store={store}>
      <WebSocketConnection host={daemon_rpc_ws}>
        <ThemeProvider theme={theme}>
          <CssBaseline />
          <ModalDialog />
          <Spinner />
          <Router />
        </ThemeProvider>
      </WebSocketConnection>
    </Provider>
  );
}
