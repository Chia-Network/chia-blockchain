import isElectron from 'is-electron';
import { i18n } from '@lingui/core';
import * as actions from '../modules/websocket';
import {
  registerService,
  getGenesisChallengeStatus,
} from '../modules/daemon_messages';
import { handle_message } from './middleware_api';
import { service_plotter } from '../util/service_names';

const crypto = require('crypto');

const callback_map = {};
if (isElectron()) {
  var { remote } = window.require('electron');
  var fs = remote.require('fs');
  var WS = window.require('ws');
}

const outgoing_message = (command, data, destination) => ({
  command,
  data,
  ack: false,
  origin: 'wallet_ui',
  destination,
  request_id: crypto.randomBytes(32).toString('hex'),
});

const socketMiddleware = () => {
  let socket = null;
  let connected = false;

  const onOpen = (store, wsConnectInterval) => (event) => {
    clearInterval(wsConnectInterval);
    connected = true;
    store.dispatch(actions.wsConnected(event.target.url));
    store.dispatch(registerService('wallet_ui'));
    store.dispatch(registerService(service_plotter));
    store.dispatch(getGenesisChallengeStatus());
  };

  const onClose = (store) => () => {
    connected = false;
    store.dispatch(actions.wsDisconnected());
  };

  const onMessage = (store) => (event) => {
    const payload = JSON.parse(event.data);
    const { request_id } = payload;
    const action = callback_map[request_id];
    if (action) {
      delete callback_map[request_id];
      const { resolve, reject } = action;
      const error = payload?.data?.error;
      const successFalse = payload?.data?.success === false;
      if (error || successFalse) {
        const errorMessage = error ?? i18n._('Unknown error');
        reject(new Error(errorMessage));
      } else {
        resolve(payload);
      }
    }
    handle_message(store, payload, action?.usePromiseReject);
  };

  return (store) => (next) => (action) => {
    switch (action.type) {
      case 'WS_CONNECT':
        const wsConnectInterval = setInterval(() => {
          if (
            socket !== null &&
            (socket.readyState == 0 || socket.readyState == 1)
          ) {
            console.log('Already connected, not reconnecting.');
            console.log(socket.readyState);
            return;
          }
          // connect to the remote host
          try {
            const key_path = remote.getGlobal('key_path');
            const cert_path = remote.getGlobal('cert_path');

            const options = {
              cert: fs.readFileSync(cert_path),
              key: fs.readFileSync(key_path),
              rejectUnauthorized: false,
            };
            socket = new WS(action.host, options);
          } catch {
            connected = false;
            store.dispatch(actions.wsDisconnected());
            console.log('Failed connection to', action.host);
            return;
          }

          // websocket handlers
          socket.onmessage = onMessage(store);
          socket.onclose = onClose(store);
          socket.addEventListener('open', onOpen(store, wsConnectInterval));
        }, 1000);
        break;
      case 'WS_DISCONNECT':
        if (socket !== null) {
          socket.close();
        }
        socket = null;
        break;
      case 'OUTGOING_MESSAGE':
        if (connected) {
          const message = outgoing_message(
            action.message.command,
            action.message.data,
            action.message.destination,
          );
          if (action.resolve) {
            callback_map[message.request_id] = action;
          }
          socket.send(JSON.stringify(message));
        } else {
          console.log('Socket not connected');
        }
        return next(action);
      default:
        return next(action);
    }
  };
};

export default socketMiddleware();
