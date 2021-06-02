import type Group from '../types/Group';
import { create_pool_wallet, collect_self_pooling_rewards, async_api } from './message';
import { getPoolState } from './farmerMessages';

export function createPoolNFT(initialTargetState, fee?: string) {
  return async (dispatch) => {
    console.log('createPoolNFT', initialTargetState, fee);
    const { data } = await async_api(
      dispatch,
      create_pool_wallet(initialTargetState, fee),
      false,
    );

    console.log('createPoolNFT response', data);

    await dispatch(getPoolState());

    return data;
  };
}

export function collectSelfPoolingRewards(walletId: number, fee?: string) {
  return async (dispatch) => {
    console.log('collectSelfPoolingRewards', walletId, fee);
    const { data } = await async_api(
      dispatch,
      collect_self_pooling_rewards(walletId, fee),
      false,
    );

    await dispatch(getPoolState());

    return data;
  };
}

const mockedDetails = {
  p2_singleton_puzzle_hash: 'asdfsadfsadfsdfadsfaf',
  points_found_since_start: 14,
  points_acknowledged_since_start: 1425,
  current_points_balance: 5,
  current_difficulty: 8,
  pool_info: {
    pool_name: 'Super Pool',
    pool_description: 'Join our pool and get rewards like a boss',
  },
};

export function updatePlotNFTs(plotNFTs: Group[]) {
  return {
    type: 'PLOT_NFT_UPDATE',
    plotNFTs,
  };
}

type GroupState = {
  groups?: Group[];
};

const initialState: GroupState = {
  /*
  groups: [
    {
      id: '1',
      self: false,
      name: 'Plot NFT A',
      poolUrl: 'http://poolin.com/info',
      state: 'FREE',
      balance: 0,
      address: 'xch1rdgndazfzqn6qf0kt4a62k4zq6ny6altk0rfssy4xtavfysvupyq389a57',
      ...mockedDetails,
    },
    {
      id: '2',
      self: true,
      name: 'Plot NFT B',
      state: 'POOLING',
      balance: 0,
      address: 'xch1rdgndazfzqn6qf0kt4a62k4zq6ny6altk0rfssy4xtavfysvupyq389a57',
      ...mockedDetails,
    },
    {
      id: '3',
      self: false,
      name: 'Plot NFT C',
      poolUrl: 'http://poolin2.com/info',
      state: 'ESCAPING',
      balance: 0,
      address: 'xch1rdgndazfzqn6qf0kt4a62k4zq6ny6altk0rfssy4xtavfysvupyq389a57',
      ...mockedDetails,
    },
  ],
  */
};

export default function groupReducer(
  state = { ...initialState },
  action: any,
): GroupState {
  switch (action.type) {
    case 'PLOT_NFT_UPDATE':
      return {
        ...state,
        groups: action.plotNFTs,
      };
    default:
      return state;
  }
}
