import * as actions from '../modules/websocket';
import {
  registerService,
  startService,
  startServiceTest,
} from '../modules/daemon_messages';
import { handle_message } from './middleware_api';
import {
  service_wallet,
  service_full_node,
  service_simulator,
  service_plotter,
  service_farmer,
  service_harvester,
} from '../util/service_names';

const crypto = require('crypto');
const config = require('../config/config');

const callback_map = {};

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

  const onOpen = (store) => (event) => {
    connected = true;
    store.dispatch(actions.wsConnected(event.target.url));
    store.dispatch(registerService('wallet_ui'));
    store.dispatch(registerService(service_plotter));

    store.dispatch(startServiceTest(service_wallet));

    if (config.local_test) {
      store.dispatch(startService(service_simulator));
    } else {
      store.dispatch(startService(service_full_node));
      store.dispatch(startService(service_farmer));
      store.dispatch(startService(service_harvester));
    }
  };

  const onClose = (store) => () => {
    connected = false;
    store.dispatch(actions.wsDisconnected());
  };

  const onMessage = (store) => (event) => {
    const payload = JSON.parse(event.data);
    const { request_id } = payload;
    if (callback_map[request_id] != null) {
      const callback_action = callback_map[request_id];
      const callback = callback_action.resolve_callback;
      callback(payload);
      callback_map[request_id] = null;
    }
    handle_message(store, payload);
  };

  return (store) => (next) => (action) => {
    switch (action.type) {
      case 'WS_CONNECT':
        if (socket !== null) {
          socket.close();
        }

        // connect to the remote host
        try {
          socket = new WebSocket(action.host);
        } catch {
          console.log('Failed connection to', action.host);
          break;
        }

        // websocket handlers
        socket.onmessage = onMessage(store);
        socket.onclose = onClose(store);
        socket.addEventListener('open', onOpen(store));
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
          if (action.resolve_callback != null) {
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
