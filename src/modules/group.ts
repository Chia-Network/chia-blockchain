import type Group from '../types/Group';

export async function createGroup() {};

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


type GroupState = {
  groups?: Group[];
};

const initialState: GroupState = {
  groups: [
    {
      id: '1',
      self: false,
      name: 'Group A',
      poolUrl: 'http://poolin.com/info',
      state: 'FREE',
      balance: 0,
      address: 'xch1rdgndazfzqn6qf0kt4a62k4zq6ny6altk0rfssy4xtavfysvupyq389a57',
      ...mockedDetails,
    },
    {
      id: '2',
      self: true,
      name: 'Group B',
      state: 'POOLING',
      balance: 0,
      address: 'xch1rdgndazfzqn6qf0kt4a62k4zq6ny6altk0rfssy4xtavfysvupyq389a57',
      ...mockedDetails,
    },
    {
      id: '3',
      self: false,
      name: 'Group C',
      poolUrl: 'http://poolin2.com/info',
      state: 'ESCAPING',
      balance: 0,
      address: 'xch1rdgndazfzqn6qf0kt4a62k4zq6ny6altk0rfssy4xtavfysvupyq389a57',
      ...mockedDetails,
    },
  ],
};

export default function groupReducer(
  state = { ...initialState },
  action: any,
): GroupState {
  const { queue } = action;

  switch (action.type) {
    case 'POOL_GROUP_INIT':
      return {
        ...state,
        groups: action.groups,
      };
    default:
      return state;
  }
}
