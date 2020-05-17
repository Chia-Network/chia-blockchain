import * as actions from "../modules/websocket";
import {
  registerService,
  startService
} from "../modules/message";
import { handle_message } from "./middleware_api";
import { config_testing } from "../config";
import {
  service_wallet_server,
  service_full_node,
  service_simulator
} from "../util/service_names";

const crypto = require("crypto");

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
    store.dispatch(actions.wsConnected(event.target.url));
    var register_action = registerService();
    store.dispatch(register_action);

    let start_wallet, start_node;
    if (config_testing) {
      start_wallet = startService(
        service_wallet_server + " --testing=true"
      );
      start_node = startService(service_simulator);
    } else {
      start_wallet = startService(service_wallet_server);
      start_node = startService(service_full_node);
    }

    store.dispatch(start_wallet);
    store.dispatch(start_node);
    // console.log("Register Service");
  };

  const onClose = store => () => {
    store.dispatch(actions.wsDisconnected());
  };

  const onMessage = store => event => {
    const payload = JSON.parse(event.data);
    handle_message(store, payload);
  };

  return store => next => action => {
    switch (action.type) {
      case "WS_CONNECT":
        if (socket !== null) {
          socket.close();
        }

        // connect to the remote host
        socket = new WebSocket(action.host);

        // websocket handlers
        socket.onmessage = onMessage(store);
        socket.onclose = onClose(store);
        socket.onopen = onOpen(store);
        connected = true;
        break;
      case "WS_DISCONNECT":
        if (socket !== null) {
          socket.close();
        }
        socket = null;
        break;
      case "OUTGOING_MESSAGE":
        if (connected) {
          // console.log("socket" + socket);
          // console.log(
          //   "Action command" + action.command + " data" + action.data
          // );
          const message = outgoing_message(
            action.command,
            action.data,
            action.destination
          );
          // console.log(message);
          socket.send(JSON.stringify(message));
        } else {
          // console.log("Socket not connected");
        }
        break;
      default:
        return next(action);
    }
  };
};

export default socketMiddleware();
