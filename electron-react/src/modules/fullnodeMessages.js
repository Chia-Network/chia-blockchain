import { service_full_node } from '../util/service_names';

export const fullNodeMessage = () => ({
  type: 'OUTGOING_MESSAGE',
  message: {
    destination: service_full_node,
  },
});

export const pingFullNode = () => {
  const action = fullNodeMessage();
  action.message.command = 'ping';
  action.message.data = {};
  return action;
};

export const getBlockChainState = () => {
  const action = fullNodeMessage();
  action.message.command = 'get_blockchain_state';
  action.message.data = {};
  return action;
};

export const getLatestBlocks = () => {
  const action = fullNodeMessage();
  action.message.command = 'get_latest_block_headers';
  action.message.data = {};
  return action;
};

export const getFullNodeConnections = () => {
  const action = fullNodeMessage();
  action.message.command = 'get_connections';
  action.message.data = {};
  return action;
};

export const openConnection = (host, port) => {
  const action = fullNodeMessage();
  action.message.command = 'open_connection';
  action.message.data = { host, port };
  return action;
};

export const closeConnection = (node_id) => {
  const action = fullNodeMessage();
  action.message.command = 'close_connection';
  action.message.data = { node_id };
  return action;
};

export const getBlock = (header_hash) => {
  const action = fullNodeMessage();
  action.message.command = 'get_block';
  action.message.data = { header_hash };
  return action;
};

export const getHeader = (header_hash) => {
  const action = fullNodeMessage();
  action.message.command = 'get_header';
  action.message.data = { header_hash };
  return action;
};

export const clearBlock = (header_hash) => {
  const action = {
    type: 'CLEAR_BLOCK',
    command: 'clear_block',
  };
  return action;
};
