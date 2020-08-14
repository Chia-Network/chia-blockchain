import * as actions from "../modules/websocket";
import {
  registerService,
  startService,
  isServiceRunning,
  startServiceTest
} from "../modules/daemon_messages";
import { handle_message } from "./middleware_api";
import {
  service_wallet,
  service_full_node,
  service_simulator,
  service_plotter
} from "../util/service_names";
const config = require("../config");

const crypto = require("crypto");

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

        // connect to the remote host
        try {
          socket = new WebSocket(action.host);
        } catch {
          console.log("Failed connection to", action.host);
          break;
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
