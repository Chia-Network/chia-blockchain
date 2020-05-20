import { service_farmer, service_harvester } from "../util/service_names";

const initial_state = {
  farmer: {
    latest_challenges: [],
    connections: [],
    open_connection_error: ""
  },
  harvester: {
    plots: []
  }
};

export const farmingReducer = (state = { ...initial_state }, action) => {
  switch (action.type) {
    case "INCOMING_MESSAGE":
      if (
        action.message.origin !== service_farmer &&
        action.message.origin !== service_harvester
      ) {
        return state;
      }
      const message = action.message;
      const data = message.data;
      const command = message.command;

      // Farmer API
      if (command === "get_latest_challenges") {
        if (data.success === false) {
          return state;
        }
        state.farmer.latest_challenges = data.latest_challenges;
        return state;
      }
      if (
        command === "get_connections" &&
        action.message.origin === service_farmer
      ) {
        if (data.success) {
          state.farmer.connections = data.connections;
          return state;
        }
      }
      if (
        command === "open_connection" &&
        action.message.origin === service_farmer
      ) {
        if (data.success) {
          state.farmer.open_connection_error = "";
        } else {
          state.farmer.open_connection_error = data.error;
        }
        return state;
      }

      // Harvester API
      if (command === "get_plots") {
        if (data.success !== true) {
          return state;
        }
        state.harvester.plots = data.plots;
        state.harvester.failed_to_open_filenames =
          data.failed_to_open_filenames;
        state.harvester.not_found_filenames = data.not_found_filenames;
        return state;
      }

      return state;
    default:
      return state;
  }
};
