import {
  service_wallet,
  service_full_node,
  service_simulator,
  service_daemon,
  service_farmer,
  service_harvester,
  service_plotter
} from "../util/service_names";

const initial_state = {
  daemon_running: false,
  daemon_connected: false,
  wallet_running: false,
  wallet_connected: false,
  full_node_running: false,
  full_node_connected: false,
  farmer_running: false,
  farmer_connected: false,
  harvester_running: false,
  harvester_connected: false,
  plotter_running: false
};

export const daemonReducer = (state = { ...initial_state }, action) => {
  switch (action.type) {
    case "INCOMING_MESSAGE":
      if (
        action.message.origin !== service_daemon &&
        action.message.command !== "ping"
      ) {
        return state;
      }
      const message = action.message;
      const data = message.data;
      const command = message.command;
      if (command === "register_service") {
        state.daemon_running = true;
        state.daemon_connected = true;
      } else if (command === "start_service") {
        const service = data.service;
        if (service === service_full_node) {
          state.full_node_running = true;
        } else if (service === service_simulator) {
          state.full_node_running = true;
        } else if (service === service_wallet) {
          state.wallet_running = true;
        } else if (service === service_farmer) {
          state.farmer_running = true;
        } else if (service === service_harvester) {
          state.harvester_running = true;
        }
      } else if (command === "ping") {
        const origin = message.origin;
        if (origin === service_full_node) {
          state.full_node_connected = true;
        } else if (origin === service_simulator) {
          state.full_node_connected = true;
        } else if (origin === service_wallet) {
          state.wallet_connected = true;
        } else if (origin === service_farmer) {
          state.farmer_connected = true;
        } else if (origin === service_harvester) {
          state.harvester_connected = true;
        }
      } else if (command === "is_running") {
        if (data.success) {
          const service = data.service;
          if (service === service_plotter) {
            state.plotter_running = data.is_running;
          } else if (service === service_full_node) {
            state.full_node_running = data.is_running;
          } else if (service === service_wallet) {
            state.wallet_running = data.is_running;
          } else if (service === service_farmer) {
            state.farmer_running = data.is_running;
          } else if (service === service_harvester) {
            state.harvester_running = data.is_running;
          }
        }
      } else if (command === "stop_service") {
        if (data.success) {
          if (data.service_name === service_plotter) {
            state.plotter_running = false;
          }
        }
      }
      return state;
    default:
      return state;
  }
};
