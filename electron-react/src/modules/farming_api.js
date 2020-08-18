import { service_farmer, service_harvester } from "../util/service_names";

const initial_state = {
  farmer: {
    latest_challenges: [],
    connections: [],
    open_connection_error: ""
  },
  harvester: {
    plots: [],
    not_found_filenames: [],
    failed_to_open_filenames: [],
    plot_directories: []
  }
};

export const farmingReducer = (state = { ...initial_state }, action) => {
  switch (action.type) {
    case "LOG_OUT":
      return { ...initial_state };
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
        return {
          ...state,
          farmer: { ...state.farmer, latest_challenges: data.latest_challenges }
        };
      }
      if (
        command === "get_connections" &&
        action.message.origin === service_farmer
      ) {
        if (data.success) {
          return {
            ...state,
            farmer: { ...state.farmer, connections: data.connections }
          };
        }
      }
      if (
        command === "open_connection" &&
        action.message.origin === service_farmer
      ) {
        if (data.success) {
          return {
            ...state,
            farmer: { ...state.farmer, open_connection_error: "" }
          };
        } else {
          return {
            ...state,
            farmer: { ...state.farmer, open_connection_error: data.error }
          };
        }
        return state;
      }

      // Harvester API
      if (command === "get_plots") {
        if (data.success !== true) {
          return state;
        }
        return {
          ...state,
          harvester: {
            ...state.harvester,
            plots: data.plots,
            failed_to_open_filenames: data.failed_to_open_filenames,
            not_found_filenames: data.not_found_filenames
          }
        };
      }

      if (command === "get_plot_directories") {
        if (data.success !== true) {
          return state;
        }
        return {
          ...state,
          harvester: {
            ...state.harvester,
            plot_directories: data.directories
          }
        };
      }

      return state;
    default:
      return state;
  }
};
