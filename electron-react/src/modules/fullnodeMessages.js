import { service_full_node } from "../util/service_names";

export const fullNodeMessage = () => ({
  type: "OUTGOING_MESSAGE",
  destination: service_full_node
});

export const pingFullNode = () => {
  var action = fullNodeMessage();
  action.command = "ping";
  action.data = {};
  return action;
};

export const getBlockChainState = () => {
  var action = fullNodeMessage();
  action.command = "get_blockchain_state";
  action.data = {};
  return action;
};

export const getLatestBlocks = () => {
  var action = fullNodeMessage();
  action.command = "get_latest_block_headers";
  action.data = {};
  return action;
};

export const getFullNodeConnections = () => {
  var action = fullNodeMessage();
  action.command = "get_connections";
  action.data = {};
  return action;
};

export const openConnection = (host, port) => {
  var action = fullNodeMessage();
  action.command = "open_connection";
  action.data = { host, port };
  return action;
};

export const closeConnection = node_id => {
  var action = fullNodeMessage();
  action.command = "close_connection";
  action.data = { node_id };
  return action;
};

export const getBlock = header_hash => {
  var action = fullNodeMessage();
  action.command = "get_block";
  action.data = { header_hash };
  return action;
};

export const getHeader = header_hash => {
  var action = fullNodeMessage();
  action.command = "get_header";
  action.data = { header_hash };
  return action;
};

export const clearBlock = header_hash => {
  var action = {
    type: "CLEAR_BLOCK",
    command: "clear_block"
  };
  return action;
};
