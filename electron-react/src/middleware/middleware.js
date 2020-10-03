import * as actions from "../modules/websocket";
import {
  registerService,
  startService,
  isServiceRunning,
  startServiceTest,
  getCertPaths
} from "../modules/daemon_messages";
import { handle_message } from "./middleware_api";
import {
  service_wallet,
  service_full_node,
  service_simulator,
  service_plotter
} from "../util/service_names";

import isElectron from "is-electron";
import config_util from "../util/config";
import { openDialog } from "../modules/dialogReducer";

if (isElectron()) {
  var remote = window.require("electron").remote;
  var fs = remote.require("fs");
  var WS = window.require('ws');
}

const config = require("../config");
const crypto = require("crypto");
const default_daemon_host = config_util.default_daemon_host;
const callback_map = {};

const outgoing_message = (command, data, destination) => ({
  command: command,
  data: data,
  ack: false,
  origin: "wallet_ui",
  destination: destination,
  request_id: crypto.randomBytes(32).toString("hex")
});

const socketMiddleware = () => {
  let socket = null;
  let connected = false;

  const onOpen = store => event => {
    connected = true;
    store.dispatch(actions.wsConnected(event.target.url));
    var register_action = registerService();
    store.dispatch(register_action);

    let start_wallet, start_node;
    if (config.local_test) {
      start_wallet = startServiceTest(service_wallet);
      start_node = startService(service_simulator);
    } else {
      start_wallet = startService(service_wallet);
      start_node = startService(service_full_node);
    }
    const state = store.getState()
    if (state.daemon_state.daemon_host === default_daemon_host)  {
      store.dispatch(getCertPaths());
    }
    store.dispatch(isServiceRunning(service_plotter));
    store.dispatch(start_wallet);
    store.dispatch(start_node);
  };

  const onClose = store => () => {
    connected = false;
    store.dispatch(actions.wsDisconnected());
  };

  const onMessage = store => event => {
    const payload = JSON.parse(event.data);
    const request_id = payload["request_id"];
    if (callback_map[request_id] != null) {
      const callback_action = callback_map[request_id];
      const callback = callback_action.resolve_callback;
      callback(payload);
      callback_map[request_id] = null;
    }
    handle_message(store, payload);
  };

  return store => next => action => {
    switch (action.type) {
      case "WS_CONNECT":
        if (socket !== null) {
          socket.close();
        }
        if (action.host != default_daemon_host) {
          if (!isElectron()) {
            // Show error message, can't connect to remote host from browser
            store.dispatch(
              openDialog(
                "Error!",
                "Web browser can't be used to connect to remote daemon"
              )
            );
          } else {
            const state = store.getState()
            const key_path = state.daemon_state.key_path
            const cert_path = state.daemon_state.cert_path
            var options = {
              cert: fs.readFileSync(cert_path),
              key: fs.readFileSync(key_path),
              rejectUnauthorized: false
            };
            try {
              socket = new WS(action.host, options);
            } catch (e) {
              connected = false
              store.dispatch(actions.wsDisconnected());
              console.log("Failed connection to", action.host);
              break;
            }
          }
        } else {
          // connect using regular ws
          try {
            socket = new WebSocket(action.host);
          } catch (e) {
            connected = false
            console.log("Failed connection to", action.host);
            store.dispatch(actions.wsDisconnected());
            break;
          }
        }

        // websocket handlers
        socket.onmessage = onMessage(store);
        socket.onclose = onClose(store);
        socket.onopen = onOpen(store);
        break;
      case "WS_DISCONNECT":
        if (socket !== null) {
          socket.close();
        }
        socket = null;
        break;
      case "OUTGOING_MESSAGE":
        if (connected) {
          const message = outgoing_message(
            action.message.command,
            action.message.data,
            action.message.destination
          );
          if (action.resolve_callback != null) {
            callback_map[message.request_id] = action;
          }
          socket.send(JSON.stringify(message));
        } else {
          console.log("Socket not connected");
        }
        return next(action);
      default:
        return next(action);
    }
  };
};

export default socketMiddleware();
