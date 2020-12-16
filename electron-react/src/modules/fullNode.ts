import { service_full_node } from '../util/service_names';
import type Connection from '../types/Connection';
import type Header from '../types/Header';

type FullNodeState = {
  blockchain_state?: {
    difficulty: number;
    peak?: {
      challenge_block_info_hash: string;
      challenge_vdf_output: {
        a: string;
        b: string;
      },
      deficit: number;
      farmer_puzzle_hash: string;
      fees: string;
      finished_challenge_slot_hashes: string[];
      finished_infused_challenge_slot_hashes: string[];
      finished_reward_slot_hashes: string[];
      header_hash: string;
      height: number;
      infused_challenge_vdf_output: {
        a: string;
        b: string;
      },
      overflow: boolean;
      pool_puzzle_hash: string;
      prev_block_hash: string;
      prev_hash: string;
      required_iters: string;
      reward_infusion_new_challenge: string;
      signage_point_index: number;
      sub_block_height: number;
      sub_epoch_summary_included: null
      sub_slot_iters: string;
      timestamp: string;
      total_iters: string;
      weight: string;
    };
    space: number;
    sub_slot_iters: number;
    sync: {
      sync_mode: boolean;
      sync_progress_height: number;
      sync_tip_height: number;
    };
  };
  connections: Connection[];
  open_connection_error?: string;
  headers: Header[];
  block?: string | null; // If not null, page is changed to block page
  header?: string | null;
  unfinished_sub_block_headers?: any[],
};

const initialState: FullNodeState = {
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
        console.log('get_blockchain_state', data);
        if (data.success) {
          return { ...state, blockchain_state: data.blockchain_state };
        }
      } else if (command === 'get_unfinished_sub_block_headers') {
        console.log('get_unfinished_sub_block_headers', data);
        if (data.success) {
          return { 
            ...state, 
            unfinished_sub_block_headers: data.latest_blocks,
          };
        }
      } /* else if (command === 'get_latest_block_headers') {
        if (data.success) {
          return { 
            ...state, 
            headers: data.latest_blocks 
          };
        }
      } */ else if (command === 'get_block') {
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
