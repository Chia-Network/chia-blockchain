import {
  service_farmer,
  service_harvester,
} from "../util/service_names";

const initial_state = {
  farmer: {
    latest_challenges: [],
    connections: [],
  },
  harvester: {
    plots: [],
  }
};

export const farmingReducer = (state = { ...initial_state }, action) => {
  switch (action.type) {
    case "INCOMING_MESSAGE":
      if (action.message.origin !== service_farmer &&
         action.message.origin !== service_harvester) {
        return state;
      }
      const message = action.message;
      const data = message.data;
      const command = message.command;

      // Farmer API
      if (command === "get_latest_challenges") {
        state.farmer.latest_challenges = data;
        return state;
      }
      if (command === "get_connections" && action.message.origin === service_farmer) {
        state.farmer.connections = data;
        return state;
      }

      // Harvester API
      if (command === "get_plots") {
        state.harvester.latest_challenges = data;
        return state;
      }

      return state;
    default:
      return state;
  }
};
