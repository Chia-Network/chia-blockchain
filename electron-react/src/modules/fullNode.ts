import { service_full_node } from '../util/service_names';
import type Connection from '../types/Connection';
import type Header from '../types/Header';
import type Block from '../types/Block';
import type FoliageBlock from '../types/FoliageBlock';
import type FoliageSubBlock from '../types/FoliageSubBlock';

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
      foliage_block: FoliageBlock;
      foliage_sub_block: FoliageSubBlock;
    };
  };
  connections?: Connection[];
  open_connection_error?: string;
  headers: Header[];
  block?: string | null; // If not null, page is changed to block page
  header?: string | null;
  unfinished_sub_block_headers?: any[];
  latest_blocks?: Block[];
};

const initialState: FullNodeState = {
  open_connection_error: '',
  headers: [],
  block: null, // If not null, page is changed to block page
  header: null,
};

export default function fullnodeReducer(
  state: FullNodeState = { ...initialState },
  action: any,
): FullNodeState {
  switch (action.type) {
    case 'FULL_NODE_SET_LATEST_BLOCKS':
      return {
        ...state,
        latest_blocks: action.blocks,
      };
    case 'FULL_NODE_SET_UNFINISHED_SUB_BLOCK_HEADERS':
      return {
        ...state,
        unfinished_sub_block_headers: action.headers,
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
          return { ...state, blockchain_state: data.blockchain_state };
        }
      } else if (command === 'get_block') {
        if (data.success) {
          return { ...state, block: data.block };
        }
      } else if (command === 'get_sub_block_record') {
        if (data.success) {
          return { ...state, header: data.header };
        }
      } else if (command === 'get_connections') {
        return { ...state, connections: data.connections };
      } else if (command === 'open_connection') {
        if (data.success) {
          return { ...state, open_connection_error: '' };
        }
        return { ...state, open_connection_error: data.error };
      }
      return state;
    default:
      return state;
  }
}
