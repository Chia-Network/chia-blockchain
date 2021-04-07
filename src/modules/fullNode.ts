import { get } from 'lodash';
import { service_full_node } from '../util/service_names';
import type Connection from '../types/Connection';
import type Header from '../types/Header';
// import type Block from '../types/Block';
import type SubBlock from '../types/SubBlock';
import type FoliageTransactionBlock from '../types/FoliageTransactionBlock';
import type Foliage from '../types/Foliage';

type FullNodeState = {
  blockchain_state?: {
    difficulty: number;
    space: number;
    sub_slot_iters: number;
    sync: {
      synced: boolean;
      sync_mode: boolean;
      sync_progress_height: number;
      sync_tip_height: number;
    };
    peak?: {
      height: number;
      foliage_transaction_block: FoliageTransactionBlock;
      foliage: Foliage;
    };
  };
  connections?: Connection[];
  open_connection_error?: string;
  headers: Header[];
  block?: string | null; // If not null, page is changed to block page
  header?: string | null;
  unfinished_block_headers?: any[];
  // latest_blocks?: Block[];
  latest_blocks?: SubBlock[];
  latest_peak_timestamp?: number;
};

const initialState: FullNodeState = {
  open_connection_error: '',
  headers: [],
  block: null, // If not null, page is changed to block page
  header: null,
};

function getLatestTimestamp(
  blocks?: SubBlock[],
  lastPeekTimestamp?: number,
): number | undefined {
  const timestamps = [];
  if (lastPeekTimestamp) {
    timestamps.push(lastPeekTimestamp);
  }

  if (blocks) {
    const firstBlock = blocks.find(
      (block) => !!block.foliage_transaction_block?.timestamp,
    );
    if (
      firstBlock &&
      firstBlock.foliage_transaction_block &&
      firstBlock.foliage_transaction_block.timestamp
    ) {
      timestamps.push(firstBlock.foliage_transaction_block?.timestamp);
    }
  }

  const timestampNumbers = timestamps.map((value) => {
    if (typeof value === 'string') {
      return Number.parseInt(value, 10);
    }

    return value;
  });

  return timestampNumbers.length ? Math.max(...timestampNumbers) : undefined;
}

export default function fullnodeReducer(
  state: FullNodeState = { ...initialState },
  action: any,
): FullNodeState {
  switch (action.type) {
    case 'FULL_NODE_SET_LATEST_BLOCKS':
      const { blocks } = action;

      return {
        ...state,
        latest_peak_timestamp: getLatestTimestamp(
          blocks,
          state.latest_peak_timestamp,
        ),
        latest_blocks: blocks,
      };
    case 'FULL_NODE_SET_UNFINISHED_BLOCK_HEADERS':
      return {
        ...state,
        unfinished_block_headers: action.headers,
      };
    case 'LOG_OUT':
      return { ...initialState };
    case 'CLEAR_BLOCK':
      return { ...state, block: null };
    case 'INCOMING_MESSAGE':
      if (action.message.origin !== service_full_node) {
        return state;
      }
      const { message } = action;
      const { data } = message;
      const { command } = message;

      if (command === 'get_blockchain_state') {
        if (data.success) {
          const { latest_blocks } = state;
          const timestamp = get(data, 'blockchain_state.peak.timestamp');
          const peakTimestamp = timestamp || state.latest_peak_timestamp;

          return {
            ...state,
            blockchain_state: data.blockchain_state,
            latest_peak_timestamp: getLatestTimestamp(
              latest_blocks,
              peakTimestamp,
            ),
          };
        }
      } else if (command === 'get_block') {
        if (data.success) {
          return { ...state, block: data.block };
        }
      } else if (command === 'get_block_record') {
        if (data.success) {
          return { ...state, header: data.header };
        }
      } else if (command === 'get_connections') {
        return { ...state, connections: data.connections };
      }
      return state;
    default:
      return state;
  }
}
