import {
  service_full_node,
} from "../util/service_names";

const initial_blockchain = {
  difficulty: 0,
  ips: 0,
  lca: null,
  min_iters: 0,
  sync: {
    sync_mode: false,
    sync_progress_height: 0,
    sync_tip_height: 0
  },
  tip_hashes: null,
  tips: null
};
const initial_state = {
  blockchain_state: initial_blockchain
};

export const fullnodeReducer = (state = { ...initial_state }, action) => {
  switch (action.type) {
    case "INCOMING_MESSAGE":
      if (action.message.origin !== service_full_node) {
        return state;
      }
      const message = action.message;
      const data = message.data;
      const command = message.command;

      if (command === "get_blockchain_state") {
        state.blockchain_state = data;
        return state;
      }
      return state;
    default:
      return state;
  }
};
