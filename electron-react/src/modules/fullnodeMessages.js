import { service_full_node } from "../util/service_names";

export const fullNodeMessage = () => ({
  type: "OUTGOING_MESSAGE",
  message: {
    destination: service_full_node
  }
});

export const pingFullNode = () => {
  var action = fullNodeMessage();
  action.message.command = "ping";
  action.message.data = {};
  return action;
};

export const getBlockChainState = () => {
  var action = fullNodeMessage();
  action.message.command = "get_blockchain_state";
  action.message.data = {};
  return action;
};

export const getLatestBlocks = () => {
  var action = fullNodeMessage();
  action.message.command = "get_latest_block_headers";
  action.message.data = {};
  return action;
};

export const getFullNodeConnections = () => {
  var action = fullNodeMessage();
  action.message.command = "get_connections";
  action.message.data = {};
  return action;
};

export const openConnection = (host, port) => {
  var action = fullNodeMessage();
  action.message.command = "open_connection";
  action.message.data = { host, port };
  return action;
};

export const closeConnection = node_id => {
  var action = fullNodeMessage();
  action.message.command = "close_connection";
  action.message.data = { node_id };
  return action;
};

export const getBlock = header_hash => {
  var action = fullNodeMessage();
  action.message.command = "get_block";
  action.message.data = { header_hash };
  return action;
};

export const getHeader = header_hash => {
  var action = fullNodeMessage();
  action.message.command = "get_header";
  action.message.data = { header_hash };
  return action;
};

export const clearBlock = header_hash => {
  var action = {
    type: "CLEAR_BLOCK",
    command: "clear_block"
  };
  return action;
};
