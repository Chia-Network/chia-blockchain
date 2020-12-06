import { service_farmer, service_harvester } from '../util/service_names';
import type Plot from '../types/Plot';
import type Challenge from '../types/Challenge';

type FarmingState = {
  farmer: {
    latest_challenges?: Challenge[];
    last_attempted_proofs?: Challenge[];
    connections: {
      bytes_read: number;
      bytes_written: number;
      creation_time: number;
      last_message_time: number;
      local_host: string;
      local_port: number;
      node_id: string;
      peer_host: string;
      peer_port: number;
      peer_server_port: number;
      type: number;
    }[];
    open_connection_error?: string;
  };
  harvester: {
    plots?: Plot[];
    not_found_filenames?: string[];
    failed_to_open_filenames?: string[];
    plot_directories?: string[];
  };
};

const initialState: FarmingState = {
  farmer: {
    connections: [],
    open_connection_error: '',
  },
  harvester: {},
};

export default function farmingReducer(
  state: FarmingState = { ...initialState },
  action: any,
): FarmingState {
  switch (action.type) {
    case 'LOG_OUT':
      return { ...initialState };
    case 'INCOMING_MESSAGE':
      if (
        action.message.origin !== service_farmer &&
        action.message.origin !== service_harvester
      ) {
        return state;
      }
      const { message } = action;
      const { data } = message;
      const { command } = message;

      // Farmer API
      if (command === 'get_latest_challenges') {
        if (data.success === false) {
          return state;
        }

        const { latest_challenges } = data;

        return {
          ...state,
          farmer: {
            ...state.farmer,
            latest_challenges,
          },
        };
      }
      if (
        command === 'get_connections' &&
        action.message.origin === service_farmer
      ) {
        if (data.success) {
          return {
            ...state,
            farmer: { ...state.farmer, connections: data.connections },
          };
        }
      }
      if (
        command === 'open_connection' &&
        action.message.origin === service_farmer
      ) {
        if (data.success) {
          return {
            ...state,
            farmer: { ...state.farmer, open_connection_error: '' },
          };
        }
        return {
          ...state,
          farmer: { ...state.farmer, open_connection_error: data.error },
        };
      }

      // Harvester API
      if (command === 'get_plots') {
        if (data.success !== true) {
          return state;
        }

        const { plots } = data;
        const sortedPlots = plots && [...plots].sort((a, b) => b.size - a.size);

        return {
          ...state,
          harvester: {
            ...state.harvester,
            plots: sortedPlots,
            failed_to_open_filenames: data.failed_to_open_filenames,
            not_found_filenames: data.not_found_filenames,
          },
        };
      }

      if (command === 'get_plot_directories') {
        if (data.success !== true) {
          return state;
        }
        return {
          ...state,
          harvester: {
            ...state.harvester,
            plot_directories: data.directories,
          },
        };
      }

      return state;
    default:
      return state;
  }
}
