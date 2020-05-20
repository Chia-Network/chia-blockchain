import { service_full_node } from "../util/service_names";

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
  tips: null,
  space: 0
};
const initial_state = {
  blockchain_state: initial_blockchain,
  connections: [],
  open_connection_error: "",
  headers: [],
  block: null, // If not null, page is changed to block page
  header: null
};

export const fullnodeReducer = (state = { ...initial_state }, action) => {
  switch (action.type) {
    case "CLEAR_BLOCK":
      state.block = null;
      return state;
    case "INCOMING_MESSAGE":
      if (action.message.origin !== service_full_node) {
        return state;
      }
      const message = action.message;
      const data = message.data;
      const command = message.command;

      if (command === "get_blockchain_state") {
        state.blockchain_state = data.blockchain_state;
        return state;
      } else if (command === "get_latest_block_headers") {
        if (data.success) {
          const headers = data.latest_blocks;
          state.headers = headers;
        }
        return state;
      } else if (command === "get_block") {
        if (data.success) {
          state.block = data.block;
        }
        return state;
      } else if (command === "get_header") {
        if (data.success) {
          state.header = data.header;
        }
        return state;
      } else if (command === "get_connections") {
        state.connections = data.connections;
        return state;
      }
      if (command === "open_connection") {
        if (data.success) {
          state.open_connection_error = "";
        } else {
          state.open_connection_error = data.error;
        }
        return state;
      }
      return state;
    default:
      return state;
  }
};
