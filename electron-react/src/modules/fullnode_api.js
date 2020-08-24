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
    case "LOG_OUT":
      return { ...initial_state };
    case "CLEAR_BLOCK":
      return { ...state, block: null };
    case "INCOMING_MESSAGE":
      if (action.message.origin !== service_full_node) {
        return state;
      }
      const message = action.message;
      const data = message.data;
      const command = message.command;

      if (command === "get_blockchain_state") {
        if (data.success) {
          return { ...state, blockchain_state: data.blockchain_state };
        }
      } else if (command === "get_latest_block_headers") {
        if (data.success) {
          return { ...state, headers: data.latest_blocks };
        }
      } else if (command === "get_block") {
        if (data.success) {
          return { ...state, block: data.block };
        }
      } else if (command === "get_header") {
        if (data.success) {
          return { ...state, header: data.header };
        }
      } else if (command === "get_connections") {
        return { ...state, connections: data.connections };
      } else if (command === "open_connection") {
        if (data.success) {
          return { ...state, open_connection_error: "" };
        } else {
          return { ...state, open_connection_error: data.error };
        }
      }
      return state;
    default:
      return state;
  }
};
