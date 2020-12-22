import { service_full_node } from '../util/service_names';
import { async_api } from './message';

export const fullNodeMessage = (message) => ({
  type: 'OUTGOING_MESSAGE',
  message: {
    destination: service_full_node,
    ...message,
  },
});

export function updateLatestBlocks() {
  return async (dispatch, getState) => {
    const state = getState();
    const height = state.full_node_state.blockchain_state?.peak?.foliage_block?.height; 
    if (height) {
      const blocks = await dispatch(getBlocksRecords(height));

      dispatch({
        type: 'FULL_NODE_SET_LATEST_BLOCKS',
        blocks,
      });
    }
  }
}

export function getBlocksRecords(end, count = 10) {
  return async (dispatch) => {
    const start = end - count;

    const { data: { blocks } } = await async_api(
      dispatch,
      fullNodeMessage({
        command: 'get_blocks',
        data: {
          start,
          end,
        },
      }),
      false,
    );

    return blocks.reverse();
  }
}

export function getUnfinishedSubBlockHeaders(subHeight) {
  return async (dispatch) => {
    const { data: { headers } } = await async_api(
      dispatch,
      fullNodeMessage({
        command: 'get_unfinished_sub_block_headers',
        data: {
          sub_height: subHeight,
        },
      }),
      false,
    );
      
    return headers.reverse();
  }
}

export function getSubBlockRecords(headerHash, count = 1) {
  return async (dispatch) => {
    const records = [];
    let currentHash = headerHash;

    for (let i = 0; i < count; i++) {
      const response = await async_api(
        dispatch,
        getSubBlockRecord(currentHash),
        false,
      );
      const subBlockRecord = response?.data?.sub_block_record;
      if (subBlockRecord) {
        records.push(subBlockRecord);
      }
      
      currentHash = subBlockRecord?.prev_hash;
      if (!currentHash) {
        break;
      }
    }

    return records;
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
export const getUnfinishedSubBlockHeaders = (subHeight) => {
  const action = fullNodeMessage();
  action.message.command = 'get_unfinished_sub_block_headers';
  action.message.data = { sub_height: subHeight};
  return action;
};
*/

// @deprecated
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

export const getSubBlock = (header_hash) => {
  const action = fullNodeMessage();
  action.message.command = 'get_sub_block';
  action.message.data = { header_hash };
  return action;
};

export const getSubBlockRecord = (headerHash) => {
  const action = fullNodeMessage();
  action.message.command = 'get_sub_block_record';
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
