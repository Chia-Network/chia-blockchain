import { service_full_node } from '../util/service_names';
import type Connection from '../types/Connection';
import type Header from '../types/Header';

type FullNodeState = {
  blockchain_state: {
    difficulty: number;
    ips: number;
    lca?: Header | null;
    min_iters: number;
    sync: {
      sync_mode: boolean;
      sync_progress_height: number;
      sync_tip_height: number;
    };
    tip_hashes?: string[] | null;
    tips?: Header[] | null;
    space: number;
  };
  connections: Connection[];
  open_connection_error?: string;
  headers: Header[];
  block?: string | null; // If not null, page is changed to block page
  header?: string | null;
};

const initialBlockchain = {
  difficulty: 0,
  ips: 0,
  lca: null,
  min_iters: 0,
  sync: {
    sync_mode: false,
    sync_progress_height: 0,
    sync_tip_height: 0,
  },
  tip_hashes: null,
  tips: null,
  space: 0,
};

const initialState: FullNodeState = {
  blockchain_state: initialBlockchain,
  connections: [],
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
      } else if (command === 'get_latest_block_headers') {
        if (data.success) {
          return { ...state, headers: data.latest_blocks };
        }
      } else if (command === 'get_block') {
        if (data.success) {
          return { ...state, block: data.block };
        }
      } else if (command === 'get_header') {
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
