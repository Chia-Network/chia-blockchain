import { service_full_node } from '../util/service_names';
import { async_api } from './message';

export const fullNodeMessage = (message) => ({
  type: 'OUTGOING_MESSAGE',
  message: {
    destination: service_full_node,
    ...message,
  },
});

export function getBlockRecords(end, count = 10) {
  return async (dispatch) => {
    let start = end - count;
    if (start < 0) {
      start = 0;
    }

    const {
      data: { block_records },
    } = await async_api(
      dispatch,
      fullNodeMessage({
        command: 'get_block_records',
        data: {
          start,
          end,
        },
      }),
      false,
    );

    return block_records ? block_records.reverse() : [];
  };
}

export function updateLatestBlocks() {
  return async (dispatch, getState) => {
    const state = getState();
    const height = state.full_node_state.blockchain_state?.peak?.height;
    if (height) {
      const blocks = await dispatch(getBlocksRecords(height));

      dispatch({
        type: 'FULL_NODE_SET_LATEST_BLOCKS',
        blocks,
      });
    }
  };
}

export function getBlocksRecords(end, count = 10) {
  return async (dispatch) => {
    let start = end - count;
    if (start < 0) {
      start = 0;
    }

    const {
      data: { blocks },
    } = await async_api(
      dispatch,
      fullNodeMessage({
        command: 'get_blocks',
        data: {
          start,
          end: end + 1,
        },
      }),
      false,
    );

    return blocks ? blocks.reverse() : [];
  };
}

export function updateUnfinishedSubBlockHeaders() {
  return async (dispatch, getState) => {
    const headers = await dispatch(getUnfinishedBlockHeaders());

    dispatch({
      type: 'FULL_NODE_SET_UNFINISHED_BLOCK_HEADERS',
      headers,
    });
  };
}

export function getUnfinishedBlockHeaders() {
  return async (dispatch) => {
    const {
      data: { headers },
    } = await async_api(
      dispatch,
      fullNodeMessage({
        command: 'get_unfinished_block_headers',
      }),
      false,
    );

    return headers && headers.reverse();
  };
}

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

/*
// @deprecated
export const getLatestBlocks = () => {
  const action = fullNodeMessage();
  action.message.command = 'get_latest_block_headers';
  action.message.data = {};
  return action;
};
*/

export const getFullNodeConnections = () => {
  const action = fullNodeMessage();
  action.message.command = 'get_connections';
  action.message.data = {};
  return action;
};

export const openConnection = (host, port) => {
  return async (dispatch) => {
    const { data } = await async_api(
      dispatch,
      fullNodeMessage({
        command: 'open_connection',
        data: {
          host,
          port,
        },
      }),
      true,
      true,
    );

    return data;
  };
};

export const closeConnection = (node_id) => {
  const action = fullNodeMessage();
  action.message.command = 'close_connection';
  action.message.data = { node_id };
  return action;
};

export const getBlockAction = (header_hash) => {
  const action = fullNodeMessage();
  action.message.command = 'get_block';
  action.message.data = { header_hash };
  return action;
};

export const getBlockRecordAction = (headerHash) => {
  const action = fullNodeMessage();
  action.message.command = 'get_block_record';
  action.message.data = { header_hash: headerHash };
  return action;
};

export const clearBlock = (header_hash) => {
  const action = {
    type: 'CLEAR_BLOCK',
    command: 'clear_block',
  };
  return action;
};

export function getBlock(headerHash) {
  return async (dispatch) => {
    const response = await async_api(
      dispatch,
      fullNodeMessage({
        command: 'get_block',
        data: {
          header_hash: headerHash,
        },
      }),
      false,
      true,
    );

    return response?.data?.block;
  };
}

export function getBlockRecord(headerHash) {
  return async (dispatch) => {
    const response = await async_api(
      dispatch,
      fullNodeMessage({
        command: 'get_block_record',
        data: {
          header_hash: headerHash,
        },
      }),
      false,
    );

    return response?.data?.block_record;
  };
}
