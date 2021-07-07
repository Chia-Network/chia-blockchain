import { service_farmer, service_harvester } from '../util/service_names';
import type Plot from '../types/Plot';
import type FarmingInfo from '../types/FarmingInfo';
import type SignagePoint from '../types/SignagePoint';
import type ProofsOfSpace from '../types/ProofsOfSpace';

function combineHarvesters(harvesters): {
  plots: Plot[];
  failed_to_open_filenames: string[];
  not_found_filenames: string[];
} {
  const plots: Plot[] = [];
  const failedToOpenFilenames: string[] = [];
  const notFoundFilenames: string[] = [];

  harvesters.forEach((harvester) => {
    const { plots: harvesterPlots, failed_to_open_filenames, no_key_filenames } = harvester;

    harvesterPlots.forEach((plot) => {
      plots.push({
        ...plot,
        harvester: harvester.connection,
      });
    });

    failedToOpenFilenames.push(...failed_to_open_filenames);
    notFoundFilenames.push(...no_key_filenames);
  });

  return {
    plots: plots.sort((a, b) => b.size - a.size),
    failed_to_open_filenames: failedToOpenFilenames,
    not_found_filenames: notFoundFilenames,
  };
}

type SignagePointAndProofsOfSpace = {
  sp: SignagePoint[];
  proofs: ProofsOfSpace;
};

type FarmingState = {
  farmer: {
    signage_points: SignagePointAndProofsOfSpace[];
    last_farming_info: FarmingInfo[];
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
    signage_points: [],
    last_farming_info: [],
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
      if (command === 'new_farming_info') {
        const last_farming_info = [
          data.farming_info,
          ...state.farmer.last_farming_info,
        ];
        return {
          ...state,
          farmer: {
            ...state.farmer,
            last_farming_info,
          },
        };
      }
      if (command === 'get_signage_points') {
        if (data.success === false) {
          return state;
        }
        data.signage_points.reverse();
        const { signage_points } = data;

        return {
          ...state,
          farmer: {
            ...state.farmer,
            signage_points,
          },
        };
      }
      if (command === 'new_signage_point') {
        const signage_point = data;

        const signage_points = [signage_point, ...state.farmer.signage_points];
        return {
          ...state,
          farmer: {
            ...state.farmer,
            signage_points,
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
      if (command === 'get_harvesters') {
        if (data.success !== true) {
          return state;
        }

        const { harvesters } = data;
        const combined = combineHarvesters(harvesters);

        return {
          ...state,
          harvester: {
            ...state.harvester,
            ...combined,
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
