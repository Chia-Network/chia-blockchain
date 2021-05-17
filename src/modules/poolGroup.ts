import type PoolGroup from '../types/PoolGroup';

export async function createPoolGroup() {}

type PoolGroupState = {
  pools?: PoolGroup[];
};

const initialState: PoolGroupState = {
  pools: [
    {
      id: '1',
      self: false,
      name: 'Group A',
      poolUrl: 'http://poolin.com/info',
      state: 'FREE',
      balance: 0,
      address: 'xch1rdgndazfzqn6qf0kt4a62k4zq6ny6altk0rfssy4xtavfysvupyq389a57',
    },
    {
      id: '2',
      self: true,
      name: 'Group B',
      state: 'POOLING',
      balance: 0,
      address: 'xch1rdgndazfzqn6qf0kt4a62k4zq6ny6altk0rfssy4xtavfysvupyq389a57',
    },
    {
      id: '3',
      self: false,
      name: 'Group C',
      poolUrl: 'http://poolin2.com/info',
      state: 'ESCAPING',
      balance: 0,
      address: 'xch1rdgndazfzqn6qf0kt4a62k4zq6ny6altk0rfssy4xtavfysvupyq389a57',
    },
  ],
};

export default function poolGroupReducer(
  state = { ...initialState },
  action: any,
): PoolGroupState {
  const { queue } = action;

  switch (action.type) {
    case 'POOL_GROUP_INIT':
      return {
        ...state,
        pools: action.pools,
      };
    default:
      return state;
  }
}
