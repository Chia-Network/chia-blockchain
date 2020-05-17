import {
  service_wallet_server,
  service_full_node,
  service_simulator,
  service_daemon
} from "../util/service_names";

const initial_state = {
  daemon_running: false,
  daemon_connected: false,
  wallet_running: false,
  wallet_connected: false,
  full_node_running: false,
  full_node_connected: false
};

export const daemonReducer = (state = { ...initial_state }, action) => {
  switch (action.type) {
    case "INCOMING_MESSAGE":
      if (
        action.message.origin !== service_daemon &&
        action.message.command != "ping"
      ) {
        return state;
      }
      const message = action.message;
      const data = message.data;
      const command = message.command;

      if (command === "register_service") {
        state.daemon_running = true;
        state.daemon_connected = true;
      } else if (command === "service_started") {
        const service = data.service;
        if (service === service_full_node) {
          state.full_node_running = true;
        } else if (service === service_simulator) {
          state.full_node_running = true;
        } else if (service === service_wallet_server) {
          state.wallet_running = true;
        }
      } else if (command === "ping") {
        const origin = message.origin;
        if (origin === service_full_node) {
          state.full_node_connected = true;
        } else if (origin === service_simulator) {
          state.full_node_connected = true;
        } else if (origin === service_wallet_server) {
          state.wallet_connected = true;
        }
      }
      return state;
    default:
      return state;
  }
};
